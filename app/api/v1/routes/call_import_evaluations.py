"""Evaluation routes scoped to a Call Import batch."""

from __future__ import annotations

import csv
import io
import math
import statistics
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy import desc, func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_api_key, get_organization_id
from app.models.database import (
    AIProvider,
    CallImport,
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
    Metric,
)
from app.models.enums import CallImportRowStatus, ModelProvider
from app.models.schemas import (
    CallImportEvaluationAggregateResponse,
    CallImportEvaluationBulkDelete,
    CallImportEvaluationCreate,
    CallImportEvaluationListResponse,
    CallImportEvaluationResponse,
    CallImportEvaluationRowListResponse,
    CallImportEvaluationRowResponse,
    CallImportEvaluationUpdate,
    CallImportMetricAggregate,
    CallImportMetricHistogramBucket,
    CallImportMetricSummary,
    CallImportMetricValueCount,
    MetricFlowEdge,
    MetricFlowNode,
    MetricFlowResponse,
)

router = APIRouter(
    prefix="/call-imports/{call_import_id}/evaluations",
    tags=["Call Import Evaluations"],
)


def _require_import(
    db: Session,
    call_import_id: UUID,
    organization_id: UUID,
) -> CallImport:
    call_import = (
        db.query(CallImport)
        .filter(
            CallImport.id == call_import_id,
            CallImport.organization_id == organization_id,
        )
        .first()
    )
    if not call_import:
        raise HTTPException(status_code=404, detail="Call import not found")
    return call_import


def _serialize_selected_metric_ids(value) -> List[UUID]:
    result: List[UUID] = []
    if not isinstance(value, list):
        return result
    for item in value:
        try:
            result.append(UUID(str(item)))
        except (TypeError, ValueError):
            continue
    return result


def _metrics_for_ids(db: Session, org_id: UUID, ids: List[UUID]) -> List[Metric]:
    if not ids:
        return []
    rows = (
        db.query(Metric)
        .filter(
            Metric.organization_id == org_id,
            Metric.id.in_(ids),
        )
        .all()
    )
    by_id = {row.id: row for row in rows}
    return [by_id[mid] for mid in ids if mid in by_id]


def _expand_metric_selection(
    db: Session,
    org_id: UUID,
    selected_ids: List[UUID],
) -> Tuple[List[Metric], Dict[UUID, List[Metric]]]:
    """Resolve user-supplied metric ids into actual leaves + parent grouping.

    Rules:
      * If a parent id is in ``selected_ids`` and no specific children of
        that parent are also listed, include EVERY enabled child of that
        parent.
      * If a parent id AND some of its children are listed, include only
        the listed children (treat the parent selection as the
        "container" so users can deselect labels).
      * Standalone metrics (no parent, no children) pass through
        unchanged.
      * Disabled metrics are filtered out at this layer so the caller
        doesn't have to repeat the check.

    Returns:
        (effective_metrics, parent_to_children)

        ``effective_metrics`` is the deduplicated list of metrics the
        worker will actually score (children + standalone). Order is
        preserved from ``selected_ids`` for display stability.

        ``parent_to_children`` maps each parent metric id (UUID) to the
        list of its selected children. Useful for grouping in the LLM
        prompt builder.
    """
    if not selected_ids:
        return [], {}

    requested = list(selected_ids)
    initial_rows = (
        db.query(Metric)
        .filter(
            Metric.organization_id == org_id,
            Metric.id.in_(requested),
        )
        .all()
    )
    initial_by_id = {row.id: row for row in initial_rows}

    parent_ids_requested = {
        m.id for m in initial_rows if m.selection_mode and not m.parent_metric_id
    }
    # Map parent id -> children explicitly requested by the user.
    explicit_children_by_parent: Dict[UUID, List[Metric]] = {}
    for m in initial_rows:
        if m.parent_metric_id and m.parent_metric_id in parent_ids_requested:
            explicit_children_by_parent.setdefault(
                m.parent_metric_id, []
            ).append(m)

    # For parents without explicit children, hydrate every enabled child.
    parents_needing_full_expansion = [
        pid
        for pid in parent_ids_requested
        if pid not in explicit_children_by_parent
    ]
    auto_expanded_children: Dict[UUID, List[Metric]] = {}
    if parents_needing_full_expansion:
        for pid in parents_needing_full_expansion:
            child_rows = (
                db.query(Metric)
                .filter(
                    Metric.organization_id == org_id,
                    Metric.parent_metric_id == pid,
                    Metric.enabled.is_(True),
                )
                .order_by(Metric.created_at.asc())
                .all()
            )
            auto_expanded_children[pid] = child_rows

    parent_to_children: Dict[UUID, List[Metric]] = {}
    for pid in parent_ids_requested:
        children = explicit_children_by_parent.get(
            pid
        ) or auto_expanded_children.get(pid, [])
        # Drop disabled children so the worker doesn't waste a slot on
        # them. Empty parents (no enabled children) are still tracked
        # because the UI may want to show "0 of 0" rather than swallow
        # them silently.
        parent_to_children[pid] = [c for c in children if c.enabled]

    effective: List[Metric] = []
    seen: set[UUID] = set()
    for mid in requested:
        m = initial_by_id.get(mid)
        if m is None:
            continue
        if m.selection_mode and not m.parent_metric_id:
            # Parent row itself is not scored — only its children.
            for child in parent_to_children.get(m.id, []):
                if child.id in seen or not child.enabled:
                    continue
                seen.add(child.id)
                effective.append(child)
            continue
        if m.parent_metric_id and m.parent_metric_id in parent_ids_requested:
            # Already accounted for via the parent expansion above.
            continue
        if not m.enabled:
            continue
        if m.id in seen:
            continue
        seen.add(m.id)
        effective.append(m)

    return effective, parent_to_children


def _serialize_eval(db: Session, row: CallImportEvaluation) -> CallImportEvaluationResponse:
    selected_ids = _serialize_selected_metric_ids(row.selected_metric_ids)

    # Pull every metric referenced anywhere in the run's grouping (leaves,
    # standalone, AND parents from selected_metric_groups) so the UI can
    # render parent labels even when only children were materialized into
    # selected_metric_ids.
    groups_raw: Dict[str, List[str]] = {}
    if isinstance(row.selected_metric_groups, dict):
        for parent_str, children in row.selected_metric_groups.items():
            if not isinstance(children, list):
                continue
            cleaned: List[str] = []
            for c in children:
                try:
                    UUID(str(c))
                    cleaned.append(str(c))
                except (TypeError, ValueError):
                    continue
            try:
                UUID(parent_str)
                groups_raw[parent_str] = cleaned
            except (TypeError, ValueError):
                continue

    metric_ids_for_lookup: List[UUID] = list(selected_ids)
    for parent_str in groups_raw.keys():
        try:
            pid = UUID(parent_str)
            if pid not in metric_ids_for_lookup:
                metric_ids_for_lookup.append(pid)
        except (TypeError, ValueError):
            continue

    metrics = _metrics_for_ids(
        db, row.organization_id, metric_ids_for_lookup
    )

    return CallImportEvaluationResponse(
        id=row.id,
        call_import_id=row.call_import_id,
        organization_id=row.organization_id,
        name=row.name,
        selected_metric_ids=selected_ids,
        selected_metric_groups=groups_raw or None,
        metrics=[
            CallImportMetricSummary(
                id=metric.id,
                name=metric.name,
                metric_type=metric.metric_type,
                description=metric.description,
                parent_metric_id=metric.parent_metric_id,
                selection_mode=metric.selection_mode,
            )
            for metric in metrics
        ],
        status=row.status,
        total_rows=row.total_rows,
        completed_rows=row.completed_rows,
        failed_rows=row.failed_rows,
        error_message=row.error_message,
        llm_provider=row.llm_provider,
        llm_model=row.llm_model,
        llm_credential_id=row.llm_credential_id,
        metric_llm_overrides=(
            row.metric_llm_overrides
            if isinstance(row.metric_llm_overrides, dict)
            else None
        ),
        stt_provider=row.stt_provider,
        stt_model=row.stt_model,
        stt_credential_id=row.stt_credential_id,
        started_at=row.started_at,
        finished_at=row.finished_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _normalize_name(value: Optional[str]) -> Optional[str]:
    """Trim user-supplied name; empty string becomes ``NULL``."""
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def _rollup_evaluation_status(evaluation: CallImportEvaluation, db: Session) -> None:
    """Recompute counters + terminal status after rows are added/removed.

    Mirrors the rollup logic in
    ``app.workers.tasks.evaluate_call_import_row._rollup_parent`` so the
    parent stays consistent even when the user manually deletes a row.
    """

    rows = (
        db.query(CallImportEvaluationRow.status)
        .filter(CallImportEvaluationRow.evaluation_id == evaluation.id)
        .all()
    )
    total = len(rows)
    completed = sum(1 for (status,) in rows if status == "completed")
    failed = sum(1 for (status,) in rows if status == "failed")
    in_progress = sum(
        1 for (status,) in rows if status in {"pending", "running"}
    )

    evaluation.total_rows = total
    evaluation.completed_rows = completed
    evaluation.failed_rows = failed

    if total == 0:
        # No rows left → treat as completed (empty result set) so the UI
        # doesn't keep polling a zombie "running" evaluation.
        evaluation.status = "completed"
        return
    if in_progress > 0:
        evaluation.status = "running"
        return
    if failed == 0:
        evaluation.status = "completed"
    elif completed == 0:
        evaluation.status = "failed"
    else:
        evaluation.status = "partial"


@router.post(
    "",
    response_model=CallImportEvaluationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="createCallImportEvaluation",
)
async def create_call_import_evaluation(
    call_import_id: UUID,
    payload: CallImportEvaluationCreate,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportEvaluationResponse:
    del api_key
    call_import = _require_import(db, call_import_id, organization_id)

    metric_ids = payload.metric_ids
    if not metric_ids:
        raise HTTPException(
            status_code=400,
            detail="Select at least one metric to run the evaluation against.",
        )

    org_metrics = (
        db.query(Metric)
        .filter(
            Metric.organization_id == organization_id,
            Metric.id.in_(metric_ids),
        )
        .all()
    )
    by_id = {metric.id: metric for metric in org_metrics}
    unknown_ids = [mid for mid in metric_ids if mid not in by_id]
    if unknown_ids:
        raise HTTPException(
            status_code=400,
            detail=(
                "These metric ids do not exist in your organization: "
                f"{', '.join(str(mid) for mid in unknown_ids)}. "
                "Refresh the metrics list and try again."
            ),
        )
    # Parents themselves are containers, not scored rows, so a disabled
    # parent shouldn't block the run as long as it has enabled children.
    # We only reject disabled rows that the worker will actually try to
    # evaluate (children + standalone leaves).
    disabled_leaves = [
        metric
        for metric in org_metrics
        if not metric.enabled
        and not (metric.selection_mode and not metric.parent_metric_id)
    ]
    if disabled_leaves:
        names = ", ".join(metric.name for metric in disabled_leaves)
        raise HTTPException(
            status_code=400,
            detail=(
                f"These metrics are disabled and cannot be evaluated: {names}. "
                "Enable them on the Metrics page (or pick different ones) and "
                "try again."
            ),
        )

    # Expand hierarchical selection: parents auto-include their enabled
    # children, mixed parent+child selections respect the user's subset.
    effective_metrics, parent_to_children = _expand_metric_selection(
        db, organization_id, metric_ids
    )
    if not effective_metrics:
        raise HTTPException(
            status_code=400,
            detail=(
                "None of the selected metrics yielded an enabled leaf to "
                "evaluate. Check that parent categories have enabled "
                "children, then try again."
            ),
        )

    # The effective list (children + standalone leaves) is what gets
    # persisted to ``selected_metric_ids`` and scored by the worker.
    # The original parents are preserved in ``selected_metric_groups``
    # so the UI can rebuild the tree later.
    leaf_metric_ids: List[UUID] = [m.id for m in effective_metrics]
    selected_metric_groups: Dict[str, List[str]] = {
        str(pid): [str(c.id) for c in children]
        for pid, children in parent_to_children.items()
    }
    metric_rows = effective_metrics
    valid_metric_id_strs = {str(m.id) for m in metric_rows}

    # ----- Validate run-level + per-metric LLM config -----
    llm_provider_norm: Optional[str] = None
    llm_model_norm: Optional[str] = None
    if payload.llm_provider or payload.llm_model:
        if not (payload.llm_provider and payload.llm_model):
            raise HTTPException(
                status_code=400,
                detail="Both llm_provider and llm_model are required when overriding the run LLM.",
            )
        try:
            llm_provider_norm = ModelProvider(
                payload.llm_provider.lower()
            ).value
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unknown LLM provider '{payload.llm_provider}'. "
                    "Valid keys are documented in ModelProvider."
                ),
            )
        llm_model_norm = payload.llm_model.strip() or None
        if not llm_model_norm:
            raise HTTPException(
                status_code=400, detail="llm_model cannot be empty."
            )

    if payload.llm_credential_id is not None:
        cred = (
            db.query(AIProvider)
            .filter(
                AIProvider.id == payload.llm_credential_id,
                AIProvider.organization_id == organization_id,
            )
            .first()
        )
        if not cred:
            raise HTTPException(
                status_code=400,
                detail=(
                    "The provided llm_credential_id does not exist in this "
                    "organization."
                ),
            )

    # Per-metric overrides: keys can be either a leaf metric id (applies
    # to that metric only) or a parent metric id (applies to every
    # child of that parent). Parent keys are expanded to their
    # children so the worker only sees concrete leaf ids.
    metric_overrides_payload: Optional[Dict[str, Dict[str, Any]]] = None
    if payload.metric_llm_overrides:
        metric_overrides_payload = {}
        for metric_id, override in payload.metric_llm_overrides.items():
            target_leaf_ids: List[str] = []
            if metric_id in valid_metric_id_strs:
                target_leaf_ids = [metric_id]
            else:
                # Maybe it's a parent id — expand to the children that
                # are part of THIS run.
                try:
                    parent_uuid = UUID(metric_id)
                except (TypeError, ValueError):
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "metric_llm_overrides references metric "
                            f"{metric_id} which is not a valid UUID."
                        ),
                    )
                children_for_parent = parent_to_children.get(parent_uuid)
                if not children_for_parent:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "metric_llm_overrides references metric "
                            f"{metric_id} which is not in metric_ids."
                        ),
                    )
                target_leaf_ids = [str(c.id) for c in children_for_parent]

            override_dict: Dict[str, Any] = {}
            if override.provider is not None:
                if not override.model:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"Override for metric {metric_id} has a provider "
                            "but no model."
                        ),
                    )
                try:
                    override_dict["provider"] = ModelProvider(
                        override.provider.lower()
                    ).value
                except ValueError:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"Override for metric {metric_id} uses unknown "
                            f"provider '{override.provider}'."
                        ),
                    )
                override_dict["model"] = override.model.strip()
            elif override.model:
                # Model without provider doesn't make sense — treat as 400
                # so the UI can fix it instead of silently falling back.
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Override for metric {metric_id} has a model but "
                        "no provider."
                    ),
                )
            if override.credential_id is not None:
                override_dict["credential_id"] = str(override.credential_id)
            if override_dict:
                for leaf_id in target_leaf_ids:
                    metric_overrides_payload[leaf_id] = override_dict

    # ----- Validate auto-transcribe settings -----
    auto_transcribe = payload.auto_transcribe and bool(payload.stt_provider)
    stt_provider_norm: Optional[str] = None
    stt_model_norm: Optional[str] = None
    if auto_transcribe:
        if not payload.stt_model:
            raise HTTPException(
                status_code=400,
                detail="stt_model is required when auto_transcribe is true.",
            )
        try:
            stt_provider_norm = ModelProvider(
                payload.stt_provider.lower()
            ).value
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown STT provider '{payload.stt_provider}'.",
            )
        stt_model_norm = payload.stt_model.strip() or None

    completed_rows = (
        db.query(CallImportRow)
        .filter(
            CallImportRow.call_import_id == call_import.id,
            CallImportRow.status == CallImportRowStatus.COMPLETED,
        )
        .order_by(CallImportRow.row_index.asc())
        .all()
    )

    evaluation = CallImportEvaluation(
        call_import_id=call_import.id,
        organization_id=organization_id,
        name=_normalize_name(payload.name),
        selected_metric_ids=[str(metric_id) for metric_id in leaf_metric_ids],
        selected_metric_groups=selected_metric_groups or None,
        status="pending",
        total_rows=len(completed_rows),
        completed_rows=0,
        failed_rows=0,
        llm_provider=llm_provider_norm,
        llm_model=llm_model_norm,
        llm_credential_id=payload.llm_credential_id,
        metric_llm_overrides=metric_overrides_payload,
        stt_provider=stt_provider_norm,
        stt_model=stt_model_norm,
        stt_credential_id=payload.stt_credential_id if auto_transcribe else None,
    )
    db.add(evaluation)
    db.flush()

    eval_rows: List[Tuple[CallImportEvaluationRow, CallImportRow]] = []
    for source_row in completed_rows:
        eval_row = CallImportEvaluationRow(
            evaluation_id=evaluation.id,
            call_import_row_id=source_row.id,
            status="pending",
            metric_scores={},
        )
        db.add(eval_row)
        eval_rows.append((eval_row, source_row))

    db.commit()
    db.refresh(evaluation)

    if not eval_rows:
        evaluation.status = "completed"
        db.commit()
        db.refresh(evaluation)
        return _serialize_eval(db, evaluation)

    # ------------------------------------------------------------------
    # Decide per-row whether to chain transcribe -> evaluate, or just
    # enqueue evaluate immediately. We prefer chaining over a single
    # ``chord`` because some rows already have transcripts and shouldn't
    # be transcribed again — chaining lets each row pick its own path
    # without one slow / failed transcription holding up the rest.
    # ------------------------------------------------------------------

    transcribe_targets: List[Tuple[CallImportEvaluationRow, CallImportRow]] = []
    eval_only_rows: List[CallImportEvaluationRow] = []
    if auto_transcribe:
        for eval_row, source_row in eval_rows:
            existing = (source_row.transcript or "").strip()
            has_recording = bool((source_row.recording_s3_key or "").strip())
            if not has_recording:
                eval_only_rows.append(eval_row)
                continue
            if existing and not payload.transcribe_overwrite:
                eval_only_rows.append(eval_row)
                continue
            transcribe_targets.append((eval_row, source_row))
    else:
        eval_only_rows = [er for er, _ in eval_rows]

    # Lazy imports keep test setup simple — tests stub the worker module so
    # importing the route never reaches into Celery's broker config.
    from app.workers.tasks.evaluate_call_import_row import (
        evaluate_call_import_row_task,
    )
    from celery import group

    try:
        if auto_transcribe and transcribe_targets:
            from app.workers.tasks.transcribe_call_import_row import (
                transcribe_call_import_row_task,
            )

            for eval_row, source_row in transcribe_targets:
                source_row.transcript_status = "pending"
                source_row.transcript_error = None
            db.commit()

            for eval_row, source_row in transcribe_targets:
                transcribe_call_import_row_task.delay(
                    str(source_row.id),
                    stt_provider_norm,
                    stt_model_norm,
                    str(payload.stt_credential_id)
                    if payload.stt_credential_id
                    else None,
                    payload.stt_language,
                    payload.transcribe_overwrite,
                    str(eval_row.id),
                )

        if eval_only_rows:
            group(
                [
                    evaluate_call_import_row_task.s(str(eval_row.id))
                    for eval_row in eval_only_rows
                ]
            ).apply_async()

        evaluation.status = "running"
    except Exception as exc:  # noqa: BLE001 — surface but don't 500
        logger.exception(
            "Failed to enqueue evaluation {} for call import {}",
            evaluation.id,
            call_import.id,
        )
        evaluation.status = "failed"
        evaluation.error_message = f"Failed to enqueue evaluation: {exc}"
    db.commit()
    db.refresh(evaluation)
    return _serialize_eval(db, evaluation)


@router.get(
    "",
    response_model=CallImportEvaluationListResponse,
    operation_id="listCallImportEvaluations",
)
async def list_call_import_evaluations(
    call_import_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportEvaluationListResponse:
    del api_key
    _require_import(db, call_import_id, organization_id)
    rows = (
        db.query(CallImportEvaluation)
        .filter(
            CallImportEvaluation.call_import_id == call_import_id,
            CallImportEvaluation.organization_id == organization_id,
        )
        .order_by(desc(CallImportEvaluation.created_at))
        .all()
    )
    return CallImportEvaluationListResponse(
        items=[_serialize_eval(db, row) for row in rows],
        total=len(rows),
    )


@router.get(
    "/{eval_id}",
    response_model=CallImportEvaluationResponse,
    operation_id="getCallImportEvaluation",
)
async def get_call_import_evaluation(
    call_import_id: UUID,
    eval_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportEvaluationResponse:
    del api_key
    _require_import(db, call_import_id, organization_id)
    row = (
        db.query(CallImportEvaluation)
        .filter(
            CallImportEvaluation.id == eval_id,
            CallImportEvaluation.call_import_id == call_import_id,
            CallImportEvaluation.organization_id == organization_id,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Call import evaluation not found")
    return _serialize_eval(db, row)


@router.get(
    "/{eval_id}/rows",
    response_model=CallImportEvaluationRowListResponse,
    operation_id="listCallImportEvaluationRows",
)
async def list_call_import_evaluation_rows(
    call_import_id: UUID,
    eval_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    q: Optional[str] = Query(
        None,
        description=(
            "Free-text search across external_call_id and transcript "
            "(case-insensitive substring match)."
        ),
    ),
    metric_id: Optional[UUID] = Query(
        None,
        description=(
            "If set, only return rows whose ``metric_scores[metric_id].value`` "
            "exactly matches ``metric_value`` (string-compared). "
            "Use together with ``metric_value``."
        ),
    ),
    metric_value: Optional[str] = Query(
        None,
        description="Value to match against metric_id (string compare).",
    ),
    status_filter: Optional[str] = Query(
        None,
        alias="status",
        description="Restrict to rows with this evaluation row status.",
    ),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportEvaluationRowListResponse:
    del api_key
    _require_import(db, call_import_id, organization_id)

    eval_row = (
        db.query(CallImportEvaluation)
        .filter(
            CallImportEvaluation.id == eval_id,
            CallImportEvaluation.call_import_id == call_import_id,
            CallImportEvaluation.organization_id == organization_id,
        )
        .first()
    )
    if not eval_row:
        raise HTTPException(status_code=404, detail="Call import evaluation not found")

    query = (
        db.query(CallImportEvaluationRow, CallImportRow)
        .join(CallImportRow, CallImportRow.id == CallImportEvaluationRow.call_import_row_id)
        .filter(CallImportEvaluationRow.evaluation_id == eval_id)
    )

    # --- Filters ----------------------------------------------------------
    if q and q.strip():
        needle = f"%{q.strip()}%"
        query = query.filter(
            or_(
                CallImportRow.external_call_id.ilike(needle),
                CallImportRow.transcript.ilike(needle),
            )
        )

    if status_filter:
        # The CallImportEvaluationRow.status column is a string in PG so a
        # plain == filter works; we lowercase to match the stored values.
        query = query.filter(
            CallImportEvaluationRow.status == status_filter.strip().lower()
        )

    if metric_id is not None and metric_value is not None:
        # ``metric_scores`` is a JSONB column shaped like
        # ``{"<metric_id>": {"value": <X>, "type": "boolean", ...}}``. We
        # extract the nested ``value`` as text and compare to the user
        # input as a string — that handles bool/int/enum without needing
        # per-type casts. ``metric_value`` is matched case-insensitively
        # so chart clicks on labels like "True" survive any casing drift
        # between worker output and the chart label.
        path_value = func.json_extract_path_text(
            CallImportEvaluationRow.metric_scores,
            str(metric_id),
            "value",
        )
        query = query.filter(func.lower(path_value) == metric_value.strip().lower())

    query = query.order_by(CallImportRow.row_index.asc())
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()

    items: List[CallImportEvaluationRowResponse] = []
    for eval_row_obj, source_row in rows:
        items.append(
            CallImportEvaluationRowResponse(
                id=eval_row_obj.id,
                evaluation_id=eval_row_obj.evaluation_id,
                call_import_row_id=eval_row_obj.call_import_row_id,
                row_index=source_row.row_index,
                external_call_id=source_row.external_call_id,
                transcript=source_row.transcript,
                raw_columns=source_row.raw_columns,
                recording_url=source_row.recording_url,
                recording_s3_key=source_row.recording_s3_key,
                status=eval_row_obj.status,
                metric_scores=eval_row_obj.metric_scores or {},
                error_message=eval_row_obj.error_message,
                started_at=eval_row_obj.started_at,
                finished_at=eval_row_obj.finished_at,
                created_at=eval_row_obj.created_at,
                updated_at=eval_row_obj.updated_at,
            )
        )

    return CallImportEvaluationRowListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{eval_id}/export",
    operation_id="exportCallImportEvaluationCsv",
)
async def export_call_import_evaluation_csv(
    call_import_id: UUID,
    eval_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    del api_key
    call_import = _require_import(db, call_import_id, organization_id)

    evaluation = (
        db.query(CallImportEvaluation)
        .filter(
            CallImportEvaluation.id == eval_id,
            CallImportEvaluation.call_import_id == call_import_id,
            CallImportEvaluation.organization_id == organization_id,
        )
        .first()
    )
    if not evaluation:
        raise HTTPException(status_code=404, detail="Call import evaluation not found")

    selected_metric_ids = _serialize_selected_metric_ids(evaluation.selected_metric_ids)
    # Include parent metric ids referenced in selected_metric_groups so
    # the export shows a parent "Chosen Label" column next to its
    # children's true/false columns.
    lookup_ids: List[UUID] = list(selected_metric_ids)
    groups_raw = (
        evaluation.selected_metric_groups
        if isinstance(evaluation.selected_metric_groups, dict)
        else {}
    )
    for parent_str in groups_raw.keys():
        try:
            pid = UUID(parent_str)
            if pid not in lookup_ids:
                lookup_ids.append(pid)
        except (TypeError, ValueError):
            continue
    metrics = _metrics_for_ids(db, organization_id, lookup_ids)
    metric_names = {str(metric.id): metric.name for metric in metrics}
    metrics_by_id = {str(metric.id): metric for metric in metrics}

    mapping = call_import.column_mapping or {}
    mapped_headers = [
        mapping.get("external_call_id"),
        mapping.get("transcript"),
        mapping.get("recording_url"),
    ]
    # Standard + extras columns: header == CSV header == raw_columns key.
    standard_export_headers: List[str] = []
    for header in [*mapped_headers, *(call_import.extra_columns or [])]:
        if isinstance(header, str) and header and header not in standard_export_headers:
            standard_export_headers.append(header)

    # Custom mapping: header in the export is the uploader-chosen name,
    # but the value is pulled from raw_columns under the original CSV header.
    custom_mapping = call_import.custom_column_mapping or {}
    custom_export: List[tuple[str, str]] = []  # [(export_header, csv_header)]
    if isinstance(custom_mapping, dict):
        for name, csv_header in custom_mapping.items():
            if not isinstance(name, str) or not isinstance(csv_header, str):
                continue
            if not name or not csv_header:
                continue
            if name in standard_export_headers:
                continue  # would clobber a real column
            custom_export.append((name, csv_header))

    # Build the metric columns in a hierarchy-aware order: each parent
    # (if any) gets a column, then its children appear directly after it
    # so the export reads like the metrics tree. Standalone metrics keep
    # their original ordering.
    metric_headers: List[str] = []
    rationale_headers: Dict[str, str] = {}  # metric_id_str -> rationale column name
    seen_metric_ids: set[str] = set()

    def _add_metric_column(metric: Metric) -> None:
        mid_str = str(metric.id)
        if mid_str in seen_metric_ids:
            return
        seen_metric_ids.add(mid_str)
        header = metric_names[mid_str]
        metric_headers.append(header)
        if bool(getattr(metric, "capture_rationale", False)):
            rationale_header = f"{header} - LLM Rationale"
            metric_headers.append(rationale_header)
            rationale_headers[mid_str] = rationale_header

    for parent_str, child_strs in groups_raw.items():
        parent = metrics_by_id.get(parent_str)
        if parent:
            _add_metric_column(parent)
        for child_str in child_strs:
            child = metrics_by_id.get(child_str)
            if child:
                _add_metric_column(child)
    # Append anything left over (standalone metrics not in any group, or
    # legacy runs without ``selected_metric_groups``).
    for metric in metrics:
        if metric.selection_mode and not metric.parent_metric_id:
            continue  # already handled above
        if str(metric.id) in seen_metric_ids:
            continue
        _add_metric_column(metric)

    fieldnames = [
        *standard_export_headers,
        *[h for h, _ in custom_export],
        *metric_headers,
    ]

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()

    rows = (
        db.query(CallImportEvaluationRow, CallImportRow)
        .join(CallImportRow, CallImportRow.id == CallImportEvaluationRow.call_import_row_id)
        .filter(CallImportEvaluationRow.evaluation_id == eval_id)
        .order_by(CallImportRow.row_index.asc())
        .all()
    )

    for eval_row, source_row in rows:
        row_out: Dict[str, str] = {}
        raw = source_row.raw_columns if isinstance(source_row.raw_columns, dict) else {}
        for header in standard_export_headers:
            value = raw.get(header)
            row_out[header] = "" if value is None else str(value)
        for export_header, csv_header in custom_export:
            value = raw.get(csv_header)
            row_out[export_header] = "" if value is None else str(value)

        scores = eval_row.metric_scores if isinstance(eval_row.metric_scores, dict) else {}
        for metric in metrics:
            metric_score = scores.get(str(metric.id)) if isinstance(scores, dict) else None
            value = metric_score.get("value") if isinstance(metric_score, dict) else None
            # Parent metrics (selection_mode set) render the chosen
            # child name for single_choice or the ";"-joined list of
            # true child names for multi_label.
            if (
                metric.selection_mode
                and not metric.parent_metric_id
                and isinstance(metric_score, dict)
            ):
                if metric.selection_mode == "multi_label":
                    selected = metric_score.get("selected_child_names")
                    if isinstance(selected, list):
                        value = ";".join(str(s) for s in selected)
                else:
                    value = (
                        metric_score.get("chosen_child_name")
                        or metric_score.get("value")
                    )
            row_out[metric.name] = "" if value is None else str(value)
            rationale_header = rationale_headers.get(str(metric.id))
            if rationale_header is not None:
                rationale = (
                    metric_score.get("rationale")
                    if isinstance(metric_score, dict)
                    else None
                )
                row_out[rationale_header] = "" if rationale is None else str(rationale)
        writer.writerow(row_out)

    # Excel on Windows defaults to the system ANSI codepage (Windows-1252)
    # when a CSV has no encoding marker, which turns UTF-8 Hindi/Devanagari
    # / any non-ASCII text into mojibake (e.g. ``ठीक`` → ``à¤ à¥€à¤•``).
    # A UTF-8 BOM tells Excel to switch to UTF-8 decoding and is silently
    # skipped by every other UTF-8-aware reader (pandas, LibreOffice,
    # Google Sheets, etc.), so the data round-trips correctly everywhere.
    csv_text = output.getvalue()
    # ``utf-8-sig`` adds the UTF-8 BOM so Excel on Windows decodes the file
    # as UTF-8 instead of the system codepage. We also declare the same
    # codec in the Content-Type header so well-behaved HTTP clients (incl.
    # ``httpx`` / ``requests`` in our tests) strip the BOM during decode.
    csv_bytes = csv_text.encode("utf-8-sig")
    filename = f"call-import-{call_import_id}-evaluation-{eval_id}.csv"
    return StreamingResponse(
        iter([csv_bytes]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.patch(
    "/{eval_id}",
    response_model=CallImportEvaluationResponse,
    operation_id="updateCallImportEvaluation",
)
async def update_call_import_evaluation(
    call_import_id: UUID,
    eval_id: UUID,
    payload: CallImportEvaluationUpdate,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportEvaluationResponse:
    """Edit metadata on an existing evaluation run (currently just ``name``)."""

    del api_key
    _require_import(db, call_import_id, organization_id)

    row = (
        db.query(CallImportEvaluation)
        .filter(
            CallImportEvaluation.id == eval_id,
            CallImportEvaluation.call_import_id == call_import_id,
            CallImportEvaluation.organization_id == organization_id,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Call import evaluation not found")

    # Treat unset vs explicit ``None`` differently: unset = leave alone,
    # explicit ``None`` or empty string = clear the name.
    payload_data = payload.model_dump(exclude_unset=True)
    if "name" in payload_data:
        row.name = _normalize_name(payload_data["name"])

    db.commit()
    db.refresh(row)
    return _serialize_eval(db, row)


def _revoke_pending_tasks(evaluation: CallImportEvaluation) -> None:
    """Best-effort cancel of any in-flight Celery tasks for an evaluation."""

    if not evaluation.celery_group_id and not any(
        r.celery_task_id for r in evaluation.row_results
    ):
        return
    try:
        from app.workers.celery_app import celery_app

        pending_task_ids = [
            eval_row.celery_task_id
            for eval_row in evaluation.row_results
            if eval_row.celery_task_id
            and eval_row.status in {"pending", "running"}
        ]
        if pending_task_ids:
            celery_app.control.revoke(pending_task_ids, terminate=False)
    except Exception:
        # Best effort — DB delete remains the source of truth.
        pass


@router.delete(
    "/{eval_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteCallImportEvaluation",
)
async def delete_call_import_evaluation(
    call_import_id: UUID,
    eval_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> Response:
    del api_key
    _require_import(db, call_import_id, organization_id)

    row = (
        db.query(CallImportEvaluation)
        .filter(
            CallImportEvaluation.id == eval_id,
            CallImportEvaluation.call_import_id == call_import_id,
            CallImportEvaluation.organization_id == organization_id,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Call import evaluation not found")

    _revoke_pending_tasks(row)

    db.delete(row)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/bulk-delete",
    status_code=status.HTTP_200_OK,
    operation_id="bulkDeleteCallImportEvaluations",
)
async def bulk_delete_call_import_evaluations(
    call_import_id: UUID,
    payload: CallImportEvaluationBulkDelete,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> Dict[str, int]:
    """Delete multiple evaluation runs scoped to one call import.

    Mirrors :func:`delete_call_import_evaluation` but in bulk so the UI
    can clear out a multi-select. Unknown ids (already deleted, or
    belonging to a different org/import) are silently skipped — the
    response just reports how many actually went away.
    """

    del api_key
    _require_import(db, call_import_id, organization_id)

    if not payload.evaluation_ids:
        return {"deleted": 0}

    rows = (
        db.query(CallImportEvaluation)
        .filter(
            CallImportEvaluation.id.in_(payload.evaluation_ids),
            CallImportEvaluation.call_import_id == call_import_id,
            CallImportEvaluation.organization_id == organization_id,
        )
        .all()
    )
    deleted = 0
    for row in rows:
        _revoke_pending_tasks(row)
        db.delete(row)
        deleted += 1
    db.commit()
    return {"deleted": deleted}


# ---------------------------------------------------------------------------
# Aggregation: turns per-row metric scores into histograms / value counts.
#
# Designed to be cheap enough to call on every page load: we read each
# evaluation row once, bucket numeric values into a fixed 10-bin
# histogram, and tally the top categorical values. Scaling concerns
# (millions of rows) are deferred — at that point we'd push this into a
# Postgres aggregate query, but for typical CSV imports (<10k rows) the
# Python pass is fast enough and dramatically simpler.
# ---------------------------------------------------------------------------


_HISTOGRAM_BUCKETS = 10
_TOP_VALUE_COUNTS = 10


def _coerce_numeric(value: Any) -> Optional[float]:
    """Return ``value`` as ``float`` when it's numeric; ``None`` otherwise."""
    if isinstance(value, bool):
        # Booleans are ints in Python; treat them as categorical so
        # pass/fail metrics show up in value_counts instead of becoming
        # a degenerate {0,1} histogram.
        return None
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    if isinstance(value, str):
        try:
            f = float(value)
            if math.isfinite(f):
                return f
        except ValueError:
            return None
    return None


def _coerce_category(value: Any) -> Optional[str]:
    """Render ``value`` as a label suitable for a value_counts bucket."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        return text or None
    # Lists / dicts: stringify so they still group sensibly without
    # exploding the cardinality (worst case: everything is "[…]" once).
    return str(value)


def _build_histogram(
    values: List[float],
) -> List[CallImportMetricHistogramBucket]:
    """Fixed-bin histogram over ``values``; returns [] for <2 values."""
    if len(values) < 2:
        return []
    lo = min(values)
    hi = max(values)
    if lo == hi:
        # All values identical — render a single bucket so the UI shows a
        # spike rather than empty space.
        return [
            CallImportMetricHistogramBucket(x0=lo, x1=hi, count=len(values))
        ]
    width = (hi - lo) / _HISTOGRAM_BUCKETS
    buckets: List[List[float]] = [[] for _ in range(_HISTOGRAM_BUCKETS)]
    for v in values:
        # Right-edge inclusive on the last bucket so ``hi`` doesn't fall
        # off into a non-existent bucket index.
        idx = int((v - lo) / width)
        if idx >= _HISTOGRAM_BUCKETS:
            idx = _HISTOGRAM_BUCKETS - 1
        buckets[idx].append(v)
    return [
        CallImportMetricHistogramBucket(
            x0=lo + i * width,
            x1=lo + (i + 1) * width,
            count=len(bucket),
        )
        for i, bucket in enumerate(buckets)
    ]


def _percentile(values: List[float], pct: float) -> Optional[float]:
    """Linear-interpolated percentile compatible with NumPy default."""
    if not values:
        return None
    sorted_vals = sorted(values)
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = (pct / 100.0) * (len(sorted_vals) - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return sorted_vals[lo]
    frac = rank - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def _compute_metric_aggregates(
    db: Session,
    evaluation: CallImportEvaluation,
    eval_rows: List[CallImportEvaluationRow],
) -> List[CallImportMetricAggregate]:
    """Collapse per-row ``metric_scores`` into one aggregate per metric.

    Selected metrics are read fresh from the DB so the response always
    surfaces the current ``metric.name`` / ``metric_type`` even when a
    metric was renamed after the run finished.
    """

    selected_ids = _serialize_selected_metric_ids(evaluation.selected_metric_ids)
    # Include parent metrics from selected_metric_groups so they appear
    # alongside their children in the aggregate response.
    groups_raw = (
        evaluation.selected_metric_groups
        if isinstance(evaluation.selected_metric_groups, dict)
        else {}
    )
    for parent_str in groups_raw.keys():
        try:
            pid = UUID(parent_str)
            if pid not in selected_ids:
                selected_ids.append(pid)
        except (TypeError, ValueError):
            continue

    metrics = _metrics_for_ids(db, evaluation.organization_id, selected_ids)
    metric_meta: Dict[str, Metric] = {str(m.id): m for m in metrics}

    # Default to selected metrics, but also include any metric ids that
    # surface in row scores even if missing from the metric registry —
    # otherwise renaming/deleting a metric mid-run would silently drop
    # results from the chart.
    discovered_ids: List[str] = list(metric_meta.keys())
    for row in eval_rows:
        scores = row.metric_scores if isinstance(row.metric_scores, dict) else {}
        for metric_id_str in scores.keys():
            if metric_id_str not in metric_meta and metric_id_str not in discovered_ids:
                discovered_ids.append(metric_id_str)

    results: List[CallImportMetricAggregate] = []

    for metric_id_str in discovered_ids:
        meta = metric_meta.get(metric_id_str)
        numeric_values: List[float] = []
        category_counts: Dict[str, int] = {}
        skipped = 0
        errored = 0
        observed_metric_type: Optional[str] = None
        observed_name: Optional[str] = None

        is_multi_label_parent = bool(
            meta
            and meta.selection_mode == "multi_label"
            and not meta.parent_metric_id
        )

        for row in eval_rows:
            scores = (
                row.metric_scores
                if isinstance(row.metric_scores, dict)
                else {}
            )
            entry = scores.get(metric_id_str)
            if not isinstance(entry, dict):
                continue
            if entry.get("metric_name"):
                observed_name = entry.get("metric_name")
            if entry.get("type"):
                observed_metric_type = entry.get("type")
            if entry.get("skipped"):
                skipped += 1
                continue
            if entry.get("error"):
                errored += 1
                continue

            # Multi-label parents store a comma-joined value that
            # isn't useful as a single category; instead tally each
            # selected child individually so the chart shows per-label
            # counts that mirror the children's own boolean histograms.
            if is_multi_label_parent:
                selected = entry.get("selected_child_names")
                if isinstance(selected, list) and selected:
                    for label in selected:
                        text_label = str(label).strip() or None
                        if text_label:
                            category_counts[text_label] = (
                                category_counts.get(text_label, 0) + 1
                            )
                continue

            value = entry.get("value")
            numeric = _coerce_numeric(value)
            if numeric is not None:
                numeric_values.append(numeric)
                continue
            category = _coerce_category(value)
            if category is not None:
                category_counts[category] = category_counts.get(category, 0) + 1

        # Build numeric stats first, then categorical (both can coexist).
        agg = CallImportMetricAggregate(
            metric_id=metric_id_str,
            metric_name=(
                (meta.name if meta else observed_name) or "Unknown metric"
            ),
            metric_type=(
                meta.metric_type if meta else observed_metric_type
            ),
            count=len(numeric_values) + sum(category_counts.values()),
            skipped_count=skipped,
            error_count=errored,
        )
        if numeric_values:
            agg.mean = float(statistics.fmean(numeric_values))
            agg.median = float(statistics.median(numeric_values))
            agg.min = min(numeric_values)
            agg.max = max(numeric_values)
            agg.stddev = (
                float(statistics.pstdev(numeric_values))
                if len(numeric_values) > 1
                else 0.0
            )
            agg.p25 = _percentile(numeric_values, 25)
            agg.p75 = _percentile(numeric_values, 75)
            agg.p95 = _percentile(numeric_values, 95)
            agg.histogram_buckets = _build_histogram(numeric_values)
        if category_counts:
            sorted_counts = sorted(
                category_counts.items(), key=lambda kv: kv[1], reverse=True
            )
            agg.value_counts = [
                CallImportMetricValueCount(label=label, count=count)
                for label, count in sorted_counts[:_TOP_VALUE_COUNTS]
            ]

        results.append(agg)

    return results


@router.get(
    "/{eval_id}/aggregate",
    response_model=CallImportEvaluationAggregateResponse,
    operation_id="getCallImportEvaluationAggregate",
)
async def get_call_import_evaluation_aggregate(
    call_import_id: UUID,
    eval_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportEvaluationAggregateResponse:
    """Return per-metric distributions for the Visualizations tab.

    The shape is intentionally chart-friendly: histograms for numeric
    metrics, top-N value counts for categorical/text metrics, plus
    summary stats (mean/p50/p95) so the UI can render summary cards
    without recomputing on the client.
    """

    del api_key
    _require_import(db, call_import_id, organization_id)

    evaluation = (
        db.query(CallImportEvaluation)
        .filter(
            CallImportEvaluation.id == eval_id,
            CallImportEvaluation.call_import_id == call_import_id,
            CallImportEvaluation.organization_id == organization_id,
        )
        .first()
    )
    if not evaluation:
        raise HTTPException(
            status_code=404, detail="Call import evaluation not found"
        )

    eval_rows = (
        db.query(CallImportEvaluationRow)
        .filter(CallImportEvaluationRow.evaluation_id == eval_id)
        .all()
    )

    metrics = _compute_metric_aggregates(db, evaluation, eval_rows)

    return CallImportEvaluationAggregateResponse(
        evaluation_id=eval_id,
        total_rows=evaluation.total_rows,
        completed_rows=evaluation.completed_rows,
        failed_rows=evaluation.failed_rows,
        metrics=metrics,
    )


# ---------------------------------------------------------------------------
# Flow chart: turns per-row LLM-inferred ``sequence`` arrays into a
# directed graph of (label -> label) transitions across the whole run.
# Powers the aggregate Sankey-style React Flow chart on the evaluation
# overview; per-call flow charts are built client-side from the same
# ``sequence`` field on a single row's metric_scores entry.
# ---------------------------------------------------------------------------


_FLOW_TERMINAL_THRESHOLD = 0.2  # Mark as terminal when >=20% of sequences end here.
_FLOW_START_NODE_ID = "__START__"


def _build_flow_graph(
    eval_rows: List[CallImportEvaluationRow],
    parent_metric: Metric,
    children: List[Metric],
) -> MetricFlowResponse:
    """Walk per-row ``sequence`` arrays and produce aggregate nodes/edges.

    A synthetic ``START`` node is prepended to every sequence so the
    diagram has a single origin. Children that never appear in any
    sequence are still emitted as nodes (count=0) so the UI can render
    them in the legend.
    """
    parent_id_str = str(parent_metric.id)
    # Build a fast lookup keyed by both the lower_snake child key (what the
    # LLM emits in ``sequence``) and the child UUID (what some clients may
    # store) so legacy / drifted payloads still resolve.
    child_lookup: Dict[str, Metric] = {}
    for child in children:
        slug = child.name.lower().replace(" ", "_")
        child_lookup[slug] = child
        child_lookup[str(child.id)] = child

    node_counts: Dict[str, int] = {}
    edge_counts: Dict[tuple[str, str], int] = {}
    terminal_counts: Dict[str, int] = {}

    total_rows = len(eval_rows)
    rows_with_sequence = 0

    for row in eval_rows:
        scores = (
            row.metric_scores if isinstance(row.metric_scores, dict) else {}
        )
        parent_entry = scores.get(parent_id_str)
        if not isinstance(parent_entry, dict):
            continue
        raw_sequence = parent_entry.get("sequence")
        if not isinstance(raw_sequence, list):
            continue

        resolved_ids: List[str] = []
        for item in raw_sequence:
            if not isinstance(item, str):
                continue
            normalized = item.strip().lower().replace(" ", "_")
            child = child_lookup.get(normalized) or child_lookup.get(item)
            if child is None:
                continue
            resolved_ids.append(str(child.id))

        if not resolved_ids:
            continue

        rows_with_sequence += 1
        for child_id in resolved_ids:
            node_counts[child_id] = node_counts.get(child_id, 0) + 1

        edge_counts[(_FLOW_START_NODE_ID, resolved_ids[0])] = (
            edge_counts.get((_FLOW_START_NODE_ID, resolved_ids[0]), 0) + 1
        )
        for src, tgt in zip(resolved_ids, resolved_ids[1:]):
            if src == tgt:
                continue
            edge_counts[(src, tgt)] = edge_counts.get((src, tgt), 0) + 1

        terminal_id = resolved_ids[-1]
        terminal_counts[terminal_id] = terminal_counts.get(terminal_id, 0) + 1

    nodes: List[MetricFlowNode] = []
    # Always include a START node so the UI has a stable entry point.
    nodes.append(
        MetricFlowNode(
            id=_FLOW_START_NODE_ID,
            label="Start",
            count=rows_with_sequence,
            is_terminal=False,
        )
    )
    for child in children:
        cid = str(child.id)
        count = node_counts.get(cid, 0)
        terminal_count = terminal_counts.get(cid, 0)
        is_terminal = False
        if rows_with_sequence > 0:
            is_terminal = (
                terminal_count / rows_with_sequence
            ) >= _FLOW_TERMINAL_THRESHOLD
        nodes.append(
            MetricFlowNode(
                id=cid,
                label=child.name,
                count=count,
                is_terminal=is_terminal,
            )
        )

    edges: List[MetricFlowEdge] = [
        MetricFlowEdge(source=src, target=tgt, count=count)
        for (src, tgt), count in sorted(
            edge_counts.items(), key=lambda kv: kv[1], reverse=True
        )
    ]

    return MetricFlowResponse(
        parent_metric_id=parent_id_str,
        parent_metric_name=parent_metric.name,
        selection_mode=parent_metric.selection_mode,
        nodes=nodes,
        edges=edges,
        total_rows=total_rows,
        rows_with_sequence=rows_with_sequence,
    )


@router.get(
    "/{eval_id}/flow",
    response_model=MetricFlowResponse,
    operation_id="getCallImportEvaluationFlow",
)
async def get_call_import_evaluation_flow(
    call_import_id: UUID,
    eval_id: UUID,
    parent_metric_id: UUID = Query(
        ...,
        description=(
            "Parent (category) metric whose children's sequences should be "
            "aggregated into a flow graph."
        ),
    ),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> MetricFlowResponse:
    """Aggregate the LLM-inferred per-row sequences into one flow graph.

    Returns ``nodes`` (one per child of the parent metric, plus a
    synthetic ``START`` node) and ``edges`` (counts of consecutive
    label transitions across every row that produced a sequence). The
    frontend feeds this directly into a React Flow / xyflow canvas;
    edge thickness should scale with ``count / total_rows`` and
    ``is_terminal`` nodes should be styled as outcomes.
    """

    del api_key
    _require_import(db, call_import_id, organization_id)

    evaluation = (
        db.query(CallImportEvaluation)
        .filter(
            CallImportEvaluation.id == eval_id,
            CallImportEvaluation.call_import_id == call_import_id,
            CallImportEvaluation.organization_id == organization_id,
        )
        .first()
    )
    if not evaluation:
        raise HTTPException(
            status_code=404, detail="Call import evaluation not found"
        )

    parent = (
        db.query(Metric)
        .filter(
            Metric.id == parent_metric_id,
            Metric.organization_id == organization_id,
        )
        .first()
    )
    if not parent:
        raise HTTPException(
            status_code=404,
            detail="Parent metric not found in this organization.",
        )
    if not parent.selection_mode:
        raise HTTPException(
            status_code=400,
            detail=(
                "Flow charts are only meaningful for parent metrics "
                "(selection_mode set). This metric is standalone."
            ),
        )

    # Children are taken from selected_metric_groups when present so the
    # flow chart reflects exactly the subset that ran in this
    # evaluation; otherwise fall back to every enabled child of the
    # parent.
    groups_raw = (
        evaluation.selected_metric_groups
        if isinstance(evaluation.selected_metric_groups, dict)
        else {}
    )
    parent_id_str = str(parent.id)
    children: List[Metric] = []
    if parent_id_str in groups_raw and isinstance(
        groups_raw[parent_id_str], list
    ):
        child_ids: List[UUID] = []
        for c in groups_raw[parent_id_str]:
            try:
                child_ids.append(UUID(str(c)))
            except (TypeError, ValueError):
                continue
        if child_ids:
            children = (
                db.query(Metric)
                .filter(
                    Metric.organization_id == organization_id,
                    Metric.id.in_(child_ids),
                )
                .order_by(Metric.created_at.asc())
                .all()
            )
    if not children:
        children = (
            db.query(Metric)
            .filter(
                Metric.organization_id == organization_id,
                Metric.parent_metric_id == parent.id,
            )
            .order_by(Metric.created_at.asc())
            .all()
        )

    eval_rows = (
        db.query(CallImportEvaluationRow)
        .filter(CallImportEvaluationRow.evaluation_id == eval_id)
        .all()
    )

    return _build_flow_graph(eval_rows, parent, children)


@router.delete(
    "/{eval_id}/rows/{eval_row_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteCallImportEvaluationRow",
)
async def delete_call_import_evaluation_row(
    call_import_id: UUID,
    eval_id: UUID,
    eval_row_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> Response:
    """Delete a single per-row scoring entry within an evaluation run.

    Useful when the user wants to drop a noisy row before re-exporting
    the CSV — e.g. a row whose audio was corrupt and skewed the
    aggregate. Counters on the parent are recomputed so the rolled-up
    status stays accurate.
    """

    del api_key
    _require_import(db, call_import_id, organization_id)

    evaluation = (
        db.query(CallImportEvaluation)
        .filter(
            CallImportEvaluation.id == eval_id,
            CallImportEvaluation.call_import_id == call_import_id,
            CallImportEvaluation.organization_id == organization_id,
        )
        .first()
    )
    if not evaluation:
        raise HTTPException(status_code=404, detail="Call import evaluation not found")

    eval_row = (
        db.query(CallImportEvaluationRow)
        .filter(
            CallImportEvaluationRow.id == eval_row_id,
            CallImportEvaluationRow.evaluation_id == eval_id,
        )
        .first()
    )
    if not eval_row:
        raise HTTPException(
            status_code=404, detail="Evaluation row not found in this run"
        )

    # If the row was still in flight, best-effort revoke the worker task
    # so it doesn't try to write into a deleted DB row mid-execution.
    if eval_row.celery_task_id and eval_row.status in {"pending", "running"}:
        try:
            from app.workers.celery_app import celery_app

            celery_app.control.revoke(eval_row.celery_task_id, terminate=False)
        except Exception:
            pass

    db.delete(eval_row)
    db.flush()
    _rollup_evaluation_status(evaluation, db)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
