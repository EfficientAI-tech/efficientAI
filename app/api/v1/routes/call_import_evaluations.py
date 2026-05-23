"""Evaluation routes scoped to a Call Import batch."""

from __future__ import annotations

import csv
import io
import json
import math
import statistics
from typing import Any, Dict, Iterator, List, Literal, Optional, Set, Tuple
from uuid import UUID

from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy import desc, func, or_, text
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.database import get_db
from app.dependencies import get_api_key, get_organization_id, require_enterprise_feature
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
    CallImportEvaluationRetryRequest,
    CallImportEvaluationRetryResponse,
    CallImportEvaluationRetrySkippedItem,
    CallImportEvaluationRowListResponse,
    CallImportEvaluationRowResponse,
    CallImportEvaluationUpdate,
    CallImportMetricAggregate,
    CallImportMetricHistogramBucket,
    CallImportMetricSummary,
    CallImportMetricValueCount,
    DiscoveredLabelDeleteRequest,
    DiscoveredLabelItem,
    DiscoveredLabelMergeRequest,
    DiscoveredLabelsResponse,
    DiscoveredMetricDeleteRequest,
    DiscoveredMetricItem,
    DiscoveredMetricMergeRequest,
    DiscoveredMetricsResponse,
    EvaluationInsightsRequest,
    EvaluationTldrSummary,
    MetricFlowEdge,
    MetricFlowNode,
    MetricFlowResponse,
)

router = APIRouter(
    prefix="/call-imports/{call_import_id}/evaluations",
    tags=["Call Import Evaluations"],
    dependencies=[Depends(require_enterprise_feature("call_imports"))],
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


def _flatten_transcript(text: Optional[str]) -> str:
    """Collapse a multi-line transcript onto a single line for spreadsheet export.

    The diarised transcript is stored as ``<speaker>: <text>`` lines joined
    by ``\\n`` because the in-app ``TranscriptView`` parses those line
    breaks to render chat bubbles. In Excel / Google Sheets that same
    newline-per-turn formatting causes each cell to balloon vertically,
    which the user reads as "lots of empty space on top of the cell".
    Flattening at export time keeps the DB shape intact while giving the
    spreadsheet a single-line cell per row.
    """
    if not text:
        return ""
    parts = [
        segment.strip()
        for segment in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ]
    return " ".join(p for p in parts if p)


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


def _serialize_eval(
    db: Session,
    row: CallImportEvaluation,
    *,
    sibling_evaluation_ids: Optional[List[UUID]] = None,
) -> CallImportEvaluationResponse:
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
                # Required by the Flow tab to know whether a parent
                # opted into discovery; without it the
                # DiscoveredLabelsPanel stays hidden even when the
                # worker is actively producing discovered_labels.
                allow_discovery=bool(
                    getattr(metric, "allow_discovery", False)
                ),
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
        diarisation_llm_provider=getattr(row, "diarisation_llm_provider", None),
        diarisation_llm_model=getattr(row, "diarisation_llm_model", None),
        diarisation_llm_credential_id=getattr(
            row, "diarisation_llm_credential_id", None
        ),
        diarisation_prompt=getattr(row, "diarisation_prompt", None),
        transcribe_mode=(
            (getattr(row, "transcribe_mode", None) or "stt_llm")
        ),
        transcript_source=(row.transcript_source or "production"),
        sibling_evaluation_ids=list(sibling_evaluation_ids or []),
        started_at=row.started_at,
        finished_at=row.finished_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        tldr_summary=_tldr_summary_payload(row),
        discover_new_metrics=bool(
            getattr(row, "discover_new_metrics", False)
        ),
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
    # Every evaluation run scores the diarised transcript and
    # auto-diarises rows that don't already have one, so STT
    # provider+model are mandatory on every request (the
    # ``auto_transcribe`` flag is preserved on the schema for API
    # compatibility but is effectively always true at this point).
    # ``transcribe_mode`` controls whether STT is required: the
    # ``llm_only`` path skips STT entirely and feeds audio directly to
    # the diariser LLM, so STT fields must be absent. The ``stt_llm``
    # path (default) keeps the original behaviour.
    transcribe_mode_norm = (payload.transcribe_mode or "stt_llm").strip().lower()
    if transcribe_mode_norm not in {"stt_llm", "llm_only"}:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown transcribe_mode '{payload.transcribe_mode}'. "
                "Expected 'stt_llm' or 'llm_only'."
            ),
        )

    auto_transcribe = True
    stt_provider_norm: Optional[str] = None
    stt_model_norm: Optional[str] = None
    if transcribe_mode_norm == "stt_llm":
        if not payload.stt_provider:
            raise HTTPException(
                status_code=400,
                detail=(
                    "stt_provider is required when "
                    "transcribe_mode='stt_llm': every evaluation run "
                    "auto-diarises rows that are missing a diarised "
                    "transcript."
                ),
            )
        if not payload.stt_model:
            raise HTTPException(
                status_code=400,
                detail=(
                    "stt_model is required when transcribe_mode='stt_llm'."
                ),
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
        if not stt_model_norm:
            raise HTTPException(
                status_code=400, detail="stt_model cannot be empty."
            )
    else:
        # llm_only — explicitly reject lingering STT inputs so the
        # contract is unambiguous (the worker would ignore them but
        # silent acceptance hides accidental misconfiguration).
        if (payload.stt_provider or "").strip() or (
            payload.stt_model or ""
        ).strip():
            raise HTTPException(
                status_code=400,
                detail=(
                    "stt_provider / stt_model must be omitted when "
                    "transcribe_mode='llm_only'; the LLM consumes the "
                    "audio directly."
                ),
            )

    # --- Validate LLM diariser settings -----
    # The post-STT diariser is mandatory now that pyannote is no longer
    # in the loop. We reject the request up-front (instead of letting
    # individual rows fail at task time) so the operator gets a clean
    # 400 in the modal.
    if not payload.diarization_llm_provider:
        raise HTTPException(
            status_code=400,
            detail=(
                "diarization_llm_provider is required: every evaluation "
                "run diarises STT output with an LLM."
            ),
        )
    if not payload.diarization_llm_model:
        raise HTTPException(
            status_code=400,
            detail=(
                "diarization_llm_model is required: every evaluation "
                "run diarises STT output with an LLM."
            ),
        )
    try:
        diarisation_llm_provider_norm: Optional[str] = ModelProvider(
            payload.diarization_llm_provider.lower()
        ).value
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown diarisation LLM provider "
                f"'{payload.diarization_llm_provider}'."
            ),
        )
    diarisation_llm_model_norm: Optional[str] = (
        payload.diarization_llm_model.strip() or None
    )
    if not diarisation_llm_model_norm:
        raise HTTPException(
            status_code=400,
            detail="diarization_llm_model cannot be empty.",
        )
    diarisation_prompt_norm: Optional[str] = (
        payload.diarization_prompt.strip()
        if isinstance(payload.diarization_prompt, str)
        else None
    ) or None

    completed_rows = (
        db.query(CallImportRow)
        .filter(
            CallImportRow.call_import_id == call_import.id,
            CallImportRow.status == CallImportRowStatus.COMPLETED,
        )
        .order_by(CallImportRow.row_index.asc())
        .all()
    )

    # Every evaluation run scores the diarised transcript. The
    # ``transcript_sources`` field on the schema has already been
    # normalized to ``['diarised']`` by the validator; we still iterate
    # the list below so the loop machinery stays generic in case future
    # sources are reintroduced.
    requested_sources: List[str] = ["diarised"]

    base_name = _normalize_name(payload.name)

    def _name_for_source(source: str) -> Optional[str]:
        # Single-source runs preserve the user's chosen name verbatim.
        del source
        return base_name

    created_evaluations: List[CallImportEvaluation] = []
    eval_row_buckets: Dict[
        UUID, List[Tuple[CallImportEvaluationRow, CallImportRow]]
    ] = {}

    for source in requested_sources:
        evaluation = CallImportEvaluation(
            call_import_id=call_import.id,
            organization_id=organization_id,
            # Mirror the parent CallImport's workspace so listings can
            # filter on workspace_id directly without joining.
            workspace_id=call_import.workspace_id,
            name=_name_for_source(source),
            selected_metric_ids=[
                str(metric_id) for metric_id in leaf_metric_ids
            ],
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
            stt_credential_id=(
                payload.stt_credential_id if auto_transcribe else None
            ),
            diarisation_llm_provider=diarisation_llm_provider_norm,
            diarisation_llm_model=diarisation_llm_model_norm,
            diarisation_llm_credential_id=(
                payload.diarization_llm_credential_id
            ),
            diarisation_prompt=diarisation_prompt_norm,
            transcribe_mode=transcribe_mode_norm,
            transcript_source=source,
            discover_new_metrics=bool(
                getattr(payload, "discover_new_metrics", False)
            ),
        )
        db.add(evaluation)
        db.flush()
        created_evaluations.append(evaluation)

        bucket: List[Tuple[CallImportEvaluationRow, CallImportRow]] = []
        for source_row in completed_rows:
            eval_row = CallImportEvaluationRow(
                evaluation_id=evaluation.id,
                call_import_row_id=source_row.id,
                status="pending",
                metric_scores={},
            )
            db.add(eval_row)
            bucket.append((eval_row, source_row))
        eval_row_buckets[evaluation.id] = bucket

    db.commit()
    for evaluation in created_evaluations:
        db.refresh(evaluation)

    primary_evaluation = created_evaluations[0]
    sibling_ids = [e.id for e in created_evaluations[1:]]

    if not completed_rows:
        for evaluation in created_evaluations:
            evaluation.status = "completed"
        db.commit()
        for evaluation in created_evaluations:
            db.refresh(evaluation)
        return _serialize_eval(
            db, primary_evaluation, sibling_evaluation_ids=sibling_ids
        )

    # ------------------------------------------------------------------
    # Auto-transcribe scheduling is shared across every requested
    # source: we only enqueue ONE diarisation per call_import_row
    # (keyed by row id), then fan that diarisation completion out to
    # every "diarised" evaluation row that's waiting for it. Production
    # evaluations skip the diarisation path entirely — they read the
    # CSV transcript which is already on the row.
    # ------------------------------------------------------------------

    # Lazy imports keep test setup simple — tests stub the worker module so
    # importing the route never reaches into Celery's broker config.
    from app.workers.tasks.evaluate_call_import_row import (
        evaluate_call_import_row_task,
    )
    from celery import group

    try:
        # Per-evaluation: figure out which eval rows can run immediately
        # vs which need to wait for diarisation. Production runs always
        # run immediately; diarised runs wait for diarisation when
        # ``auto_transcribe`` is set and the diarised transcript is
        # missing/being overwritten.
        eval_only_row_ids: List[str] = []
        # row_id -> list of (eval_row, source_row) waiting on its diarisation
        deferred_by_row: Dict[
            UUID, List[Tuple[CallImportEvaluationRow, CallImportRow]]
        ] = {}

        for evaluation in created_evaluations:
            bucket = eval_row_buckets[evaluation.id]
            is_diarised_run = evaluation.transcript_source == "diarised"
            for eval_row, source_row in bucket:
                if (
                    auto_transcribe
                    and is_diarised_run
                    and bool((source_row.recording_s3_key or "").strip())
                ):
                    existing_dia = (
                        source_row.diarised_transcript or ""
                    ).strip()
                    needs_diarise = (
                        not existing_dia or payload.transcribe_overwrite
                    )
                    if needs_diarise:
                        deferred_by_row.setdefault(
                            source_row.id, []
                        ).append((eval_row, source_row))
                        continue
                eval_only_row_ids.append(str(eval_row.id))

        # Kick off the diarisation worker once per unique row. Each call
        # carries the *first* deferred eval row id so the worker can
        # chain it on completion; remaining deferred eval rows on the
        # same source row are enqueued immediately for evaluation
        # because they'll re-read ``diarised_transcript`` once the
        # worker writes it.
        if deferred_by_row:
            from app.workers.tasks.transcribe_call_import_row import (
                transcribe_call_import_row_task,
            )

            # Mark the source rows as pending so the UI's diarisation
            # badge flips immediately, before Celery picks them up.
            for source_row_id, waiting in deferred_by_row.items():
                source_row = waiting[0][1]
                source_row.diarised_transcript_status = "pending"
                source_row.diarised_transcript_error = None
            db.commit()

            for source_row_id, waiting in deferred_by_row.items():
                primary_eval_row = waiting[0][0]
                source_row = waiting[0][1]
                transcribe_call_import_row_task.delay(
                    str(source_row.id),
                    stt_provider_norm,
                    stt_model_norm,
                    str(payload.stt_credential_id)
                    if payload.stt_credential_id
                    else None,
                    payload.stt_language,
                    payload.transcribe_overwrite,
                    str(primary_eval_row.id),
                    diarisation_llm_provider_norm,
                    diarisation_llm_model_norm,
                    str(payload.diarization_llm_credential_id)
                    if payload.diarization_llm_credential_id
                    else None,
                    diarisation_prompt_norm,
                    transcribe_mode_norm,
                )
                # Any sibling diarised evals on the same row enqueue
                # immediately — they will read the same
                # ``diarised_transcript`` once the worker finishes.
                for eval_row, _ in waiting[1:]:
                    eval_only_row_ids.append(str(eval_row.id))

        if eval_only_row_ids:
            group(
                [
                    evaluate_call_import_row_task.s(eval_row_id)
                    for eval_row_id in eval_only_row_ids
                ]
            ).apply_async()

        for evaluation in created_evaluations:
            evaluation.status = "running"
    except Exception as exc:  # noqa: BLE001 — surface but don't 500
        logger.exception(
            "Failed to enqueue evaluation(s) for call import {}",
            call_import.id,
        )
        for evaluation in created_evaluations:
            evaluation.status = "failed"
            evaluation.error_message = (
                f"Failed to enqueue evaluation: {exc}"
            )
    db.commit()
    for evaluation in created_evaluations:
        db.refresh(evaluation)
    return _serialize_eval(
        db, primary_evaluation, sibling_evaluation_ids=sibling_ids
    )


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
            "Free-text search across conversation_id and transcript "
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
    flow_parent_id: Optional[UUID] = Query(
        None,
        description=(
            "Parent (category) metric whose ``sequence`` array should be "
            "checked against ``flow_node`` and ``flow_edge_target``. Used "
            "to drill into the calls behind a flow-chart node or edge."
        ),
    ),
    flow_node: Optional[str] = Query(
        None,
        description=(
            "If set together with ``flow_parent_id``, only return rows "
            "whose sequence under that parent contains this step. Accepts "
            "either a child metric UUID (resolved to slug(name)), a "
            "``disc:<slug>`` discovered-label id, or a raw slug."
        ),
    ),
    flow_edge_target: Optional[str] = Query(
        None,
        description=(
            "Optional companion to ``flow_node``: when set, restrict to "
            "rows whose sequence contains the directed transition "
            "``flow_node -> flow_edge_target`` (immediately adjacent). "
            "Same id format as ``flow_node``."
        ),
    ),
    discovered_parent_id: Optional[UUID] = Query(
        None,
        description=(
            "Parent (category) metric that defines the discovery scope "
            "for ``discovered_label_key`` / ``has_discovered``."
        ),
    ),
    discovered_label_key: Optional[str] = Query(
        None,
        description=(
            "If set together with ``discovered_parent_id``, only return "
            "rows whose ``metric_scores[parent].discovered_labels`` "
            "list contains an entry with this slug (after applying "
            "evaluation-level merge aliases)."
        ),
    ),
    has_discovered: Optional[bool] = Query(
        None,
        description=(
            "If true together with ``discovered_parent_id``, only return "
            "rows that have at least one LLM-discovered label for the "
            "parent. Useful to triage which calls produced novel labels."
        ),
    ),
    sort_by: Optional[str] = Query(
        None,
        description=(
            "Column to sort by. Accepted values: ``row_index`` (default "
            "when omitted), ``conversation_id``, ``status`` (the "
            "evaluation-row status), or ``metric:<metric_uuid>`` to sort "
            "by ``metric_scores[<uuid>].value``. Metric sorts compare "
            "the extracted JSON text — adequate for booleans, enum "
            "labels, and 0-1 ratings; large integer values may sort "
            "lexicographically (10 before 2)."
        ),
    ),
    sort_dir: Optional[str] = Query(
        "asc",
        description="Sort direction: ``asc`` (default) or ``desc``.",
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
        # Search across both transcript columns so a hit in either the
        # production or the diarised version surfaces the row,
        # independent of which source the evaluation actually scored.
        query = query.filter(
            or_(
                CallImportRow.conversation_id.ilike(needle),
                CallImportRow.transcript.ilike(needle),
                CallImportRow.diarised_transcript.ilike(needle),
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

    # --- Flow chart drilldown filter -------------------------------------
    # Translates a clicked node (or edge) on the flow chart into a
    # SQL filter against ``metric_scores[<parent>].sequence``. The
    # frontend sends either a child UUID, a ``disc:<slug>`` discovered
    # node id, or a raw slug — we normalize all three to the slug that
    # actually appears in stored ``sequence`` arrays.
    if flow_parent_id is not None and flow_node and flow_node.strip():
        parent_id_str_local = str(flow_parent_id)
        alias_map_flow = _alias_map_for_parent(eval_row, flow_parent_id)

        def _flow_node_to_slug(raw: str) -> Optional[str]:
            raw_clean = raw.strip()
            if not raw_clean:
                return None
            if raw_clean == _FLOW_START_NODE_ID:
                # The synthetic START node isn't a real sequence entry;
                # filtering on it is meaningless so we skip silently.
                return None
            if raw_clean.startswith(_DISCOVERED_NODE_PREFIX):
                return _resolve_alias(
                    alias_map_flow,
                    _slug_label(raw_clean[len(_DISCOVERED_NODE_PREFIX) :]),
                )
            # Try to interpret as a child metric UUID first; fall back
            # to treating it as a slug.
            try:
                child_uuid = UUID(raw_clean)
            except (TypeError, ValueError):
                return _resolve_alias(alias_map_flow, _slug_label(raw_clean))
            child = (
                db.query(Metric.name)
                .filter(
                    Metric.id == child_uuid,
                    Metric.organization_id == organization_id,
                )
                .first()
            )
            if child and child[0]:
                return _resolve_alias(alias_map_flow, _slug_label(child[0]))
            return _resolve_alias(alias_map_flow, _slug_label(raw_clean))

        from_slug = _flow_node_to_slug(flow_node)
        target_slug: Optional[str] = None
        if flow_edge_target and flow_edge_target.strip():
            target_slug = _flow_node_to_slug(flow_edge_target)

        if from_slug:
            # The ``metric_scores`` column is declared as ``Column(JSON)``
            # in the model so on databases where the table was created
            # from the model (rather than the migration) the physical
            # type is ``json``, not ``jsonb``. The JSONB-only operators
            # below (``jsonb_exists``, ``jsonb_array_elements_text``,
            # ``@>``) require a JSONB input — we cast once up front so
            # the same SQL works regardless of which path created the
            # table.
            scores_jsonb = (
                "(call_import_evaluation_rows.metric_scores)::jsonb"
            )
            if target_slug:
                # Edge filter: rows whose sequence under this parent
                # contains ``from_slug`` immediately followed by
                # ``target_slug``. Implemented as a correlated EXISTS
                # over ``jsonb_array_elements_text`` with ORDINALITY,
                # which is the portable way to express "next array
                # index" against a JSONB array in Postgres.
                edge_filter_sql = text(
                    f"""
                    EXISTS (
                        SELECT 1
                        FROM jsonb_array_elements_text(
                            COALESCE(
                                {scores_jsonb} -> :p_id -> 'sequence',
                                '[]'::jsonb
                            )
                        ) WITH ORDINALITY AS s1(elem, ord)
                        JOIN jsonb_array_elements_text(
                            COALESCE(
                                {scores_jsonb} -> :p_id -> 'sequence',
                                '[]'::jsonb
                            )
                        ) WITH ORDINALITY AS s2(elem, ord)
                          ON s2.ord = s1.ord + 1
                        WHERE s1.elem = :from_slug
                          AND s2.elem = :to_slug
                    )
                    """
                ).bindparams(
                    p_id=parent_id_str_local,
                    from_slug=from_slug,
                    to_slug=target_slug,
                )
                query = query.filter(edge_filter_sql)
            else:
                # Node filter: rows whose ``metric_scores -> parent ->
                # 'sequence'`` array contains ``from_slug``. We use the
                # function form ``jsonb_exists`` rather than the ``?``
                # operator to avoid psycopg2 mistaking the question
                # mark for a parameter placeholder.
                node_filter_sql = text(
                    f"""
                    jsonb_exists(
                        COALESCE(
                            {scores_jsonb} -> :p_id -> 'sequence',
                            '[]'::jsonb
                        ),
                        :slug
                    )
                    """
                ).bindparams(p_id=parent_id_str_local, slug=from_slug)
                query = query.filter(node_filter_sql)

    # --- Discovered label filters ---------------------------------------
    # Surfaces "which calls produced THIS LLM-discovered label" and the
    # broader "which calls produced ANY LLM-discovered label". Both
    # operate on ``metric_scores[<parent>].discovered_labels`` (a list
    # of dicts) plus the same ``sequence`` array — covering both legacy
    # rows where the slug only made it into ``sequence`` and newer
    # rows where it landed in both.
    if discovered_parent_id is not None and (
        discovered_label_key or has_discovered
    ):
        d_parent_str = str(discovered_parent_id)
        alias_map_disc = _alias_map_for_parent(eval_row, discovered_parent_id)
        # See note above: cast once so the JSONB operators don't reject
        # the column when it's typed as ``json`` in the database.
        scores_jsonb = "(call_import_evaluation_rows.metric_scores)::jsonb"
        if discovered_label_key and discovered_label_key.strip():
            target = _resolve_alias(
                alias_map_disc, _slug_label(discovered_label_key)
            )
            if target:
                # Match rows whose discovered_labels list has an entry
                # ``{"key": <target>}`` OR whose sequence array still
                # contains the slug. The latter covers older rows that
                # were rewritten by a merge in the discovered_labels
                # blob but whose sequence may have lagged.
                contains_json = json.dumps(
                    {d_parent_str: {"discovered_labels": [{"key": target}]}}
                )
                disc_filter_sql = text(
                    f"""
                    (
                        {scores_jsonb} @> CAST(:contains AS JSONB)
                        OR
                        jsonb_exists(
                            COALESCE(
                                {scores_jsonb} -> :p_id -> 'sequence',
                                '[]'::jsonb
                            ),
                            :slug
                        )
                    )
                    """
                ).bindparams(
                    contains=contains_json,
                    p_id=d_parent_str,
                    slug=target,
                )
                query = query.filter(disc_filter_sql)
        elif has_discovered:
            # No specific slug — just rows that surfaced any candidate
            # under this parent. We coalesce missing paths to ``[]`` so
            # ``jsonb_array_length`` always sees an array (it raises on
            # non-array inputs, but our shape guarantees a list when
            # the key is present).
            has_disc_sql = text(
                f"""
                jsonb_array_length(
                    COALESCE(
                        {scores_jsonb} -> :p_id -> 'discovered_labels',
                        '[]'::jsonb
                    )
                ) > 0
                """
            ).bindparams(p_id=d_parent_str)
            query = query.filter(has_disc_sql)

    # --- Sorting ----------------------------------------------------------
    # Column-click sorting from the UI. Falls back to ``row_index`` so
    # paging stays stable when the user clears the sort. We always add a
    # secondary ``row_index`` tiebreaker so duplicate sort keys (e.g.
    # many rows with ``status = 'completed'``) keep a deterministic
    # order across page boundaries — without this, pagination can
    # double-show or skip rows when Postgres picks a different physical
    # order on each query.
    direction_desc = (sort_dir or "asc").strip().lower() == "desc"

    def _apply_direction(column_expr):
        return column_expr.desc() if direction_desc else column_expr.asc()

    # Whether the caller's ``sort_by`` resolved to a known column. We
    # use this flag to decide whether ``sort_dir`` is honoured on the
    # fallback path: unrecognized columns (typos, stale UI state) fall
    # back to the implicit ``row_index ASC`` default and intentionally
    # ignore ``sort_dir`` so users don't get a surprise reverse order
    # from a typo'd column name.
    sort_recognized = False
    sort_by_clean = (sort_by or "").strip()
    primary_sort = None
    if sort_by_clean == "row_index":
        sort_recognized = True
        # Falls through to the default ``order_by`` below with
        # ``primary_sort`` still None — but ``sort_recognized=True``
        # tells the fallback branch to apply the requested direction.
    elif sort_by_clean == "conversation_id":
        sort_recognized = True
        primary_sort = _apply_direction(CallImportRow.conversation_id)
    elif sort_by_clean == "status":
        sort_recognized = True
        primary_sort = _apply_direction(CallImportEvaluationRow.status)
    elif sort_by_clean.startswith("metric:"):
        raw_metric_id = sort_by_clean.split(":", 1)[1].strip()
        try:
            metric_uuid = UUID(raw_metric_id)
        except (TypeError, ValueError):
            metric_uuid = None
        if metric_uuid is not None:
            sort_recognized = True
            # ``metric_scores`` is JSON-typed but the helper functions
            # for path extraction differ between Postgres (production)
            # and SQLite (default test backend). Branch on the active
            # dialect so we can use the right primitive:
            #   * Postgres → ``json_extract_path_text(col, key, "value")``
            #     which returns the value as TEXT for both ``json`` and
            #     ``jsonb`` columns.
            #   * SQLite   → ``json_extract(col, '$."<uuid>".value')``
            #     using JSONPath syntax. ``metric_uuid`` is already
            #     validated above (``UUID(raw_metric_id)``), so the
            #     interpolated path is safe from injection.
            # NULL values (rows where the metric wasn't scored) sort
            # to the END regardless of direction so un-scored rows
            # don't crowd the top of an ascending sort.
            dialect_name = (
                db.bind.dialect.name if db.bind is not None else "postgresql"
            )
            if dialect_name == "sqlite":
                json_path = f'$."{metric_uuid}".value'
                path_value = func.json_extract(
                    CallImportEvaluationRow.metric_scores,
                    json_path,
                )
            else:
                path_value = func.json_extract_path_text(
                    CallImportEvaluationRow.metric_scores,
                    str(metric_uuid),
                    "value",
                )
            primary_sort = (
                path_value.desc().nullslast()
                if direction_desc
                else path_value.asc().nullslast()
            )

    if primary_sort is not None:
        query = query.order_by(primary_sort, CallImportRow.row_index.asc())
    elif sort_recognized:
        # Explicit ``sort_by=row_index`` request — honour direction.
        query = query.order_by(_apply_direction(CallImportRow.row_index))
    else:
        # No sort requested OR unrecognized column — safe default of
        # ``row_index ASC``. We deliberately ignore ``sort_dir`` here
        # so a typo'd / stale ``sort_by`` doesn't quietly invert the
        # default order.
        query = query.order_by(CallImportRow.row_index.asc())
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()

    # Pick the transcript that matches the parent evaluation's
    # ``transcript_source`` so the row-detail drawer naturally shows
    # the value that was actually scored. Falls back to the other
    # transcript if the chosen one is missing so the user still sees
    # context instead of an empty panel.
    eval_transcript_source = (
        (eval_row.transcript_source or "production").strip().lower()
    )

    def _pick_transcript(source_row: CallImportRow) -> Optional[str]:
        if eval_transcript_source == "diarised":
            return (
                source_row.diarised_transcript
                or source_row.transcript
            )
        return source_row.transcript or source_row.diarised_transcript

    items: List[CallImportEvaluationRowResponse] = []
    for eval_row_obj, source_row in rows:
        items.append(
            CallImportEvaluationRowResponse(
                id=eval_row_obj.id,
                evaluation_id=eval_row_obj.evaluation_id,
                call_import_row_id=eval_row_obj.call_import_row_id,
                row_index=source_row.row_index,
                conversation_id=source_row.conversation_id,
                transcript=_pick_transcript(source_row),
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
    format: Literal["csv", "xlsx"] = Query(
        "csv",
        description=(
            "Output format. ``csv`` returns a UTF-8 BOM CSV; ``xlsx`` "
            "returns a native Excel workbook (single sheet)."
        ),
    ),
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

    # Two export-time modes depending on how the batch was uploaded:
    #
    #   * Schema-driven (new): ``call_imports.schema_id`` is set,
    #     ``parameter_mapping`` records which CSV header fed each
    #     parameter, and ``raw_columns`` on each row is keyed by
    #     parameter NAME. Export headers are the parameter names.
    #   * Legacy (pre-schema): ``column_mapping`` / ``extra_columns`` /
    #     ``custom_column_mapping`` drive the columns and
    #     ``raw_columns`` is keyed by the original CSV header.
    #
    # We bucket entries into ``standard_export_headers`` (raw_columns
    # key == export header) and ``custom_export`` (export header
    # differs from the raw_columns key) so the row-projection loop
    # below stays mode-agnostic.
    standard_export_headers: List[str] = []
    custom_export: List[tuple[str, str]] = []  # [(export_header, raw_columns_key)]

    if call_import.schema_id is not None:
        # Use the live schema parameter list for column ordering. Falls
        # back to whatever's in ``parameter_mapping`` if the schema was
        # deleted (defensive - the FK is ON DELETE RESTRICT, but tests
        # / future cascades may still hit this branch).
        from app.models.database import CallImportSchema as _ImportSchema

        schema_obj = (
            db.query(_ImportSchema)
            .filter(_ImportSchema.id == call_import.schema_id)
            .first()
        )
        if schema_obj is not None:
            params_sorted = sorted(
                schema_obj.parameters, key=lambda p: p.ordering or 0
            )
            for param in params_sorted:
                if param.name and param.name not in standard_export_headers:
                    standard_export_headers.append(param.name)
        else:
            for param_name in (call_import.parameter_mapping or {}).keys():
                if param_name and param_name not in standard_export_headers:
                    standard_export_headers.append(param_name)
    else:
        mapping = call_import.column_mapping or {}
        mapped_headers = [
            mapping.get("external_call_id"),
            mapping.get("transcript"),
            mapping.get("recording_url"),
        ]
        for header in [*mapped_headers, *(call_import.extra_columns or [])]:
            if (
                isinstance(header, str)
                and header
                and header not in standard_export_headers
            ):
                standard_export_headers.append(header)

        custom_mapping = call_import.custom_column_mapping or {}
        if isinstance(custom_mapping, dict):
            for name, csv_header in custom_mapping.items():
                if not isinstance(name, str) or not isinstance(csv_header, str):
                    continue
                if not name or not csv_header:
                    continue
                if name in standard_export_headers:
                    continue  # would clobber a real column
                custom_export.append((name, csv_header))

    # Build the metric columns: each parent (if any) gets a value column
    # and (when capture_rationale=true) a "<Parent> - LLM Rationale"
    # column. The per-child boolean columns are intentionally suppressed
    # — categorization metrics now collapse to exactly two columns in
    # the export, mirroring the in-app table.
    child_ids_in_groups: set[str] = set()
    for parent_str, child_strs in groups_raw.items():
        for child_str in child_strs:
            if isinstance(child_str, str):
                child_ids_in_groups.add(child_str)

    metric_headers: List[str] = []
    rationale_headers: Dict[str, str] = {}  # metric_id_str -> rationale column name
    seen_metric_ids: set[str] = set()

    def _add_metric_column(metric: Metric) -> None:
        mid_str = str(metric.id)
        if mid_str in seen_metric_ids:
            return
        # Skip any child whose parent is part of this run — the parent
        # column above already shows the chosen child name as its
        # value.
        if mid_str in child_ids_in_groups:
            return
        seen_metric_ids.add(mid_str)
        header = metric_names[mid_str]
        metric_headers.append(header)
        if bool(getattr(metric, "capture_rationale", False)):
            rationale_header = f"{header} - LLM Rationale"
            metric_headers.append(rationale_header)
            rationale_headers[mid_str] = rationale_header

    for parent_str in groups_raw.keys():
        parent = metrics_by_id.get(parent_str)
        if parent:
            _add_metric_column(parent)
        # Children of an in-run parent are deliberately not emitted —
        # the ``child_ids_in_groups`` guard inside ``_add_metric_column``
        # is what enforces this. We still iterate the keys above (not
        # ``.items()``) so the parent-only emission is explicit.
    # Append anything left over (standalone metrics not in any group, or
    # legacy runs without ``selected_metric_groups``).
    for metric in metrics:
        if metric.selection_mode and not metric.parent_metric_id:
            continue  # already handled above
        if str(metric.id) in seen_metric_ids:
            continue
        _add_metric_column(metric)

    # Three new fixed columns surface the two transcript fields and the
    # evaluation's transcript_source as live values pulled from the
    # ``CallImportRow`` (not from the frozen ``raw_columns`` snapshot).
    # The user can now compare "what was in the CSV" vs "what the
    # diarisation worker produced" without round-tripping through the
    # UI, and downstream tools can verify which transcript the metrics
    # were computed against.
    PRODUCTION_TRANSCRIPT_HEADER = "Production Transcript"
    DIARISED_TRANSCRIPT_HEADER = "Diarised Transcript"
    EVAL_SOURCE_HEADER = "Evaluated Transcript Source"

    fieldnames = [
        *standard_export_headers,
        *[h for h, _ in custom_export],
        PRODUCTION_TRANSCRIPT_HEADER,
        DIARISED_TRANSCRIPT_HEADER,
        EVAL_SOURCE_HEADER,
        *metric_headers,
    ]

    rows = (
        db.query(CallImportEvaluationRow, CallImportRow)
        .join(CallImportRow, CallImportRow.id == CallImportEvaluationRow.call_import_row_id)
        .filter(CallImportEvaluationRow.evaluation_id == eval_id)
        .order_by(CallImportRow.row_index.asc())
        .all()
    )

    evaluated_source_label = (
        "Diarised"
        if (evaluation.transcript_source or "production") == "diarised"
        else "Production"
    )

    def _project_rows() -> Iterator[Dict[str, str]]:
        for eval_row, source_row in rows:
            row_out: Dict[str, str] = {}
            raw = (
                source_row.raw_columns
                if isinstance(source_row.raw_columns, dict)
                else {}
            )
            for header in standard_export_headers:
                value = raw.get(header)
                row_out[header] = "" if value is None else str(value)
            for export_header, csv_header in custom_export:
                value = raw.get(csv_header)
                row_out[export_header] = "" if value is None else str(value)

            # Live transcripts pulled from the row, NOT from raw_columns,
            # so re-diarised values are always reflected in the export.
            # Both transcript columns are flattened to a single line so the
            # spreadsheet cell doesn't balloon vertically — the in-app
            # ``TranscriptView`` still has the DB copy with line breaks
            # intact for chat-bubble rendering.
            row_out[PRODUCTION_TRANSCRIPT_HEADER] = _flatten_transcript(
                source_row.transcript
            )
            row_out[DIARISED_TRANSCRIPT_HEADER] = _flatten_transcript(
                source_row.diarised_transcript
            )
            row_out[EVAL_SOURCE_HEADER] = evaluated_source_label

            scores = (
                eval_row.metric_scores
                if isinstance(eval_row.metric_scores, dict)
                else {}
            )
            for metric in metrics:
                metric_score = (
                    scores.get(str(metric.id))
                    if isinstance(scores, dict)
                    else None
                )
                value = (
                    metric_score.get("value")
                    if isinstance(metric_score, dict)
                    else None
                )
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
                    row_out[rationale_header] = (
                        "" if rationale is None else str(rationale)
                    )
            yield row_out

    base_filename = f"call-import-{call_import_id}-evaluation-{eval_id}"

    if format == "xlsx":
        # xlsx is unicode-native (Hindi/Devanagari, emoji, etc.) so the
        # UTF-8-BOM dance isn't needed here. ``write_only`` mode keeps
        # peak memory bounded for large evaluations because openpyxl
        # only buffers the current row.
        try:
            from openpyxl import Workbook  # type: ignore
            from openpyxl.cell import WriteOnlyCell  # type: ignore
            from openpyxl.styles import Font  # type: ignore
        except ImportError as exc:  # pragma: no cover - exercised by pyproject lock
            raise HTTPException(
                status_code=500,
                detail=(
                    "Excel export requires the 'openpyxl' package which is "
                    "not installed."
                ),
            ) from exc

        workbook = Workbook(write_only=True)
        worksheet = workbook.create_sheet(title="Evaluation")

        bold_font = Font(bold=True)
        header_cells = []
        for header in fieldnames:
            cell = WriteOnlyCell(worksheet, value=header)
            cell.font = bold_font
            header_cells.append(cell)
        worksheet.append(header_cells)

        for row_dict in _project_rows():
            worksheet.append([row_dict.get(h, "") for h in fieldnames])

        buffer = io.BytesIO()
        workbook.save(buffer)
        xlsx_bytes = buffer.getvalue()
        filename = f"{base_filename}.xlsx"
        return StreamingResponse(
            iter([xlsx_bytes]),
            media_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row_dict in _project_rows():
        writer.writerow(row_dict)

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
    filename = f"{base_filename}.csv"
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


# ---------------------------------------------------------------------------
# User-initiated cancel for in-flight evaluation rows
# ---------------------------------------------------------------------------
#
# Evaluation rows can sit in ``running`` for many minutes when the underlying
# LLM / audio metric call is slow or wedged (the worker carries an 8 min
# soft / 10 min hard time limit). Without a cancel affordance the operator's
# only recourse is to wait for Celery's time limit to fire — or to manually
# mutate the DB. These helpers + the two endpoints below give the UI a
# first-class "Abort" button mirroring the diarisation cancel pattern at
# ``app.api.v1.routes.call_imports`` (``_apply_diarisation_cancel`` etc.).
#
# Why ``terminate=True``: the legacy ``_revoke_pending_tasks`` above uses
# ``terminate=False`` because it's called from delete-flow paths where the
# task may simply not get to run (a worker pulls it off the queue and drops
# it). For a user-initiated cancel we want SIGTERM to interrupt the worker
# mid-LLM/audio call so the in-flight HTTP request actually aborts.
# ``terminate=True`` routes the signal to the executing process; we spell
# ``signal="SIGTERM"`` out for clarity even though it's the default.

# Sentinel error message stamped on cancelled rows. Read by the eval worker's
# ``_was_cancelled_externally`` guard (see
# :mod:`app.workers.tasks.evaluate_call_import_row`) so a worker that's already
# past its slowest operation can't overwrite the cancelled state with its own
# terminal status. Touching either copy means touching both.
EVAL_CANCELLED_BY_USER_ERROR: str = "Evaluation cancelled by user"


def _cancellable_eval_states() -> Tuple[str, ...]:
    """States that an evaluation row can be cancelled from.

    Kept as a tiny helper so adding a future ``"queued"`` / ``"retrying"``
    state only needs one edit.
    """
    return ("pending", "running")


def _revoke_eval_task(eval_row: CallImportEvaluationRow) -> None:
    """Best-effort revoke of a single eval row's Celery task.

    Always swallows control-plane exceptions — Celery's control bus is
    inherently best-effort and a missed revoke is not catastrophic
    because the DB row is already flipped to ``failed`` by the caller
    before this runs (so the UI immediately reflects the cancel; if
    the task happens to finish anyway, the worker's finaliser skips
    over the row via :data:`EVAL_CANCELLED_BY_USER_ERROR`).
    """
    task_id = (eval_row.celery_task_id or "").strip()
    if not task_id:
        return
    try:
        from app.workers.celery_app import celery_app

        celery_app.control.revoke(
            task_id, terminate=True, signal="SIGTERM"
        )
        logger.info(
            "Revoked evaluation task {} for eval row {}",
            task_id,
            eval_row.id,
        )
    except Exception as exc:  # noqa: BLE001 — revoke is best-effort
        logger.warning(
            "Failed to revoke evaluation task {} for eval row {}: {}",
            task_id,
            eval_row.id,
            exc,
        )


def _apply_evaluation_cancel(
    eval_rows: List[CallImportEvaluationRow],
) -> Tuple[int, int]:
    """Cancel every cancellable row in ``eval_rows``.

    Returns ``(cancelled, skipped)`` so the caller can build a typed
    response without re-querying the DB. The caller is responsible for
    ``db.commit()`` after this returns — we deliberately don't commit
    here so a batch endpoint can flush all rows in one transaction.
    """
    cancellable_states = _cancellable_eval_states()
    cancelled = 0
    skipped = 0
    now = datetime.now(timezone.utc)
    for eval_row in eval_rows:
        if (eval_row.status or "").lower() not in cancellable_states:
            skipped += 1
            continue
        # Flip the row state BEFORE we revoke so the UI's next poll
        # already shows the cancel, even if Celery's control plane is
        # slow to ack.
        eval_row.status = "failed"
        eval_row.error_message = EVAL_CANCELLED_BY_USER_ERROR
        eval_row.finished_at = now
        _revoke_eval_task(eval_row)
        # Drop the task id so a follow-up retry (or a stale poll) can't
        # accidentally re-revoke or get confused.
        eval_row.celery_task_id = None
        cancelled += 1
    return cancelled, skipped


@router.post(
    "/{eval_id}/cancel",
    response_model=CallImportEvaluationResponse,
    status_code=status.HTTP_200_OK,
    operation_id="cancelCallImportEvaluation",
)
async def cancel_call_import_evaluation(
    call_import_id: UUID,
    eval_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportEvaluationResponse:
    """Abort all in-flight (or queued) rows in a single evaluation run.

    Idempotent: calling on a run whose rows are already terminal returns
    the run unchanged with a 200, so the UI can fire this from an
    "Abort" button without having to pre-check the state.

    Race notes:

    * Each cancellable row's ``status`` is flipped to ``failed`` with
      :data:`EVAL_CANCELLED_BY_USER_ERROR` BEFORE the Celery revoke,
      so the polling UI sees the cancel immediately.
    * If the worker happens to finish between our DB flip and the
      SIGTERM landing, its ``_was_cancelled_externally`` guard will
      detect the cancelled sentinel on the row and skip its own
      status / score writes (see
      :mod:`app.workers.tasks.evaluate_call_import_row`).
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

    _apply_evaluation_cancel(list(evaluation.row_results))
    db.flush()
    _rollup_evaluation_status(evaluation, db)
    db.commit()
    db.refresh(evaluation)
    return _serialize_eval(db, evaluation)


@router.post(
    "/{eval_id}/rows/{eval_row_id}/cancel",
    response_model=CallImportEvaluationRowResponse,
    status_code=status.HTTP_200_OK,
    operation_id="cancelCallImportEvaluationRow",
)
async def cancel_call_import_evaluation_row(
    call_import_id: UUID,
    eval_id: UUID,
    eval_row_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportEvaluationRowResponse:
    """Abort an in-flight (or queued) evaluation for a single row.

    Idempotent: calling on a row that's already terminal (``completed``
    / ``failed``) returns the row unchanged with a 200 so the UI can
    wire this to a "Stop" button without having to pre-check the
    state. Updates the parent run's rollup so its counters reflect
    the cancel immediately.
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

    _apply_evaluation_cancel([eval_row])
    db.flush()
    _rollup_evaluation_status(evaluation, db)
    db.commit()
    db.refresh(eval_row)

    source_row = (
        db.query(CallImportRow)
        .filter(CallImportRow.id == eval_row.call_import_row_id)
        .first()
    )

    return CallImportEvaluationRowResponse(
        id=eval_row.id,
        evaluation_id=eval_row.evaluation_id,
        call_import_row_id=eval_row.call_import_row_id,
        row_index=source_row.row_index if source_row else None,
        conversation_id=source_row.conversation_id if source_row else None,
        transcript=(
            (source_row.diarised_transcript or source_row.transcript)
            if source_row
            else None
        ),
        raw_columns=source_row.raw_columns if source_row else None,
        recording_url=source_row.recording_url if source_row else None,
        recording_s3_key=source_row.recording_s3_key if source_row else None,
        status=eval_row.status,
        metric_scores=eval_row.metric_scores or {},
        error_message=eval_row.error_message,
        started_at=eval_row.started_at,
        finished_at=eval_row.finished_at,
        created_at=eval_row.created_at,
        updated_at=eval_row.updated_at,
    )


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
    # alongside their children in the aggregate response. Use ``getattr``
    # with a default so the helper still works for callers that pass
    # lightweight objects (tests, in-memory shims) that don't carry the
    # attribute at all.
    groups_raw_candidate = getattr(evaluation, "selected_metric_groups", None)
    groups_raw = (
        groups_raw_candidate if isinstance(groups_raw_candidate, dict) else {}
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
        # For multi-label parents we still need to know how many rows
        # were scored (each row votes for >=1 label) so the n-badge in
        # the UI shows "n=50" instead of the misleading "n=208" sum.
        multi_label_rows_scored = 0
        skipped = 0
        errored = 0
        observed_metric_type: Optional[str] = None
        observed_name: Optional[str] = None

        # ``meta`` is a real ``Metric`` row in production, but tests
        # frequently pass a lightweight stub. Pull the two attributes
        # we need via ``getattr`` so a stub that only sets ``id`` /
        # ``name`` / ``metric_type`` doesn't blow up here.
        is_multi_label_parent = bool(
            meta
            and getattr(meta, "selection_mode", None) == "multi_label"
            and not getattr(meta, "parent_metric_id", None)
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
                    multi_label_rows_scored += 1
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

        # ``count`` is "rows scored". For numeric / single-choice
        # metrics that's the same as ``len(numeric) + sum(categories)``
        # because each scored row contributes exactly one observation.
        # Multi-label parents however contribute one observation per
        # selected child, so summing ``category_counts`` over-counts —
        # we tracked rows-scored separately above and use it here.
        rows_scored = (
            multi_label_rows_scored
            if is_multi_label_parent
            else len(numeric_values) + sum(category_counts.values())
        )

        # Build numeric stats first, then categorical (both can coexist).
        agg = CallImportMetricAggregate(
            metric_id=metric_id_str,
            metric_name=(
                (meta.name if meta else observed_name) or "Unknown metric"
            ),
            metric_type=(
                meta.metric_type if meta else observed_metric_type
            ),
            is_multi_label_parent=is_multi_label_parent,
            count=rows_scored,
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

    # Sort so each parent metric immediately precedes its children.
    # The Visualizations grid renders metrics top-to-bottom in this
    # order, so multi-label parents (the "summary" chart) sit above
    # the per-child boolean histograms that drill into them. Metrics
    # whose ``meta`` row was deleted mid-run (``meta is None``) sink
    # to the bottom but keep their relative order.
    enumerated = list(enumerate(results))

    def _sort_key(item: Tuple[int, CallImportMetricAggregate]):
        original_idx, agg = item
        meta = metric_meta.get(agg.metric_id)
        if meta is None:
            return (1, "", 1, "", original_idx)
        parent_id = getattr(meta, "parent_metric_id", None)
        # Group key: a child shares its parent's UUID; a parent
        # uses its own UUID. Within a group, depth=0 (parent) sorts
        # before depth=1 (child); ties break alphabetically by name
        # so children render in a stable order regardless of which
        # row scored which label first.
        if parent_id is None:
            group_key = str(meta.id)
            depth = 0
        else:
            group_key = str(parent_id)
            depth = 1
        return (
            0,
            group_key,
            depth,
            (getattr(meta, "name", "") or "").lower(),
            original_idx,
        )

    enumerated.sort(key=_sort_key)
    return [agg for _idx, agg in enumerated]


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
# TLDR insights: LLM-generated narrative + bullet patterns rendered above
# the Visualizations charts. Cached on ``CallImportEvaluation.tldr_summary``
# so the page never auto-burns LLM tokens; the user explicitly clicks
# "Generate summary" or "Regenerate" from the empty-state CTA.
# ---------------------------------------------------------------------------


_INSIGHTS_SYSTEM_PROMPT = (
    "You are a senior conversation-analytics reviewer. You will be "
    "given aggregated metric statistics + a sample of rationales for "
    "the rows of a single call-import evaluation. Identify the most "
    "useful PATTERNS that hold ACROSS the calls -- not just per-metric "
    "numbers. Look for combinations (e.g. `when X happens, Y also "
    "tends to happen`), notable outliers, frequent failure modes, and "
    "any signal that would change how a reviewer triages the run.\n\n"
    "Return STRICT JSON only, with this shape and no extra keys:\n"
    "{\n"
    '  "narrative": "<2-4 sentence prose summary>",\n'
    '  "patterns": ["<bullet 1>", "<bullet 2>", ...]\n'
    "}\n\n"
    "Constraints:\n"
    "- 3 to 5 bullets, each <= 200 characters, no markdown.\n"
    "- Avoid restating raw counts unless they reveal a pattern.\n"
    "- Use neutral, factual language ('frustration appeared in...') "
    "rather than judgemental ('the agents failed to...')."
)


def _tldr_summary_payload(
    evaluation: CallImportEvaluation,
) -> Optional[EvaluationTldrSummary]:
    """Return the cached TLDR (with ``is_stale`` set) or ``None``.

    ``CallImportEvaluation.tldr_summary`` is a ``JSON`` column so we
    have to validate shape defensively -- a half-written or hand-edited
    blob should not break the aggregate response. Returns ``None`` when
    no cached summary exists.
    """
    raw = evaluation.tldr_summary
    if not isinstance(raw, dict):
        return None
    narrative = raw.get("narrative")
    if not isinstance(narrative, str) or not narrative.strip():
        return None
    patterns_raw = raw.get("patterns")
    patterns = (
        [str(p) for p in patterns_raw if isinstance(p, str) and p.strip()]
        if isinstance(patterns_raw, list)
        else []
    )
    generated_at_raw = raw.get("generated_at")
    try:
        generated_at = (
            datetime.fromisoformat(generated_at_raw)
            if isinstance(generated_at_raw, str)
            else evaluation.updated_at or datetime.now(timezone.utc)
        )
    except ValueError:
        generated_at = evaluation.updated_at or datetime.now(timezone.utc)
    snapshot = raw.get("generated_at_completed_rows")
    snapshot_int = int(snapshot) if isinstance(snapshot, (int, float)) else 0
    return EvaluationTldrSummary(
        narrative=narrative.strip(),
        patterns=patterns,
        generated_at=generated_at,
        generated_at_completed_rows=snapshot_int,
        provider=raw.get("provider") if isinstance(raw.get("provider"), str) else None,
        model=raw.get("model") if isinstance(raw.get("model"), str) else None,
        is_stale=evaluation.completed_rows > snapshot_int,
    )


def _sample_rationales_per_metric(
    eval_rows: List[CallImportEvaluationRow],
    *,
    per_metric_cap: int = 3,
    rationale_char_cap: int = 600,
) -> Dict[str, List[str]]:
    """Collect up to ``per_metric_cap`` distinct rationales per metric.

    Distinctness is case- and whitespace-insensitive. We truncate each
    rationale to ``rationale_char_cap`` so a few unusually verbose rows
    can't dominate the prompt budget. Empty / non-string rationales are
    skipped.
    """
    out: Dict[str, List[str]] = {}
    seen: Dict[str, set[str]] = {}
    for row in eval_rows:
        scores = row.metric_scores if isinstance(row.metric_scores, dict) else {}
        for metric_id, entry in scores.items():
            if not isinstance(entry, dict):
                continue
            rationale = entry.get("rationale")
            if not isinstance(rationale, str):
                continue
            text = rationale.strip()
            if not text:
                continue
            bucket = out.setdefault(metric_id, [])
            if len(bucket) >= per_metric_cap:
                continue
            key = " ".join(text.lower().split())
            seen_set = seen.setdefault(metric_id, set())
            if key in seen_set:
                continue
            seen_set.add(key)
            bucket.append(text[:rationale_char_cap])
    return out


def _build_insights_messages(
    evaluation: CallImportEvaluation,
    aggregate: List[CallImportMetricAggregate],
    rationale_samples: Dict[str, List[str]],
    metric_meta: Dict[str, Metric],
) -> List[Dict[str, str]]:
    """Render the user prompt fed to the LLM.

    The shape is plain markdown-ish text instead of JSON so the LLM can
    skim it without us spending tokens on verbose schema delimiters.
    Parent metrics surface their child metrics nested underneath so the
    model sees the hierarchy and can talk about "X often co-occurred
    with Y" rather than treating sub-labels as standalone metrics.
    """
    name = evaluation.name or f"Run {str(evaluation.id)[:8]}"
    lines: List[str] = [
        f"Evaluation: {name}",
        (
            f"Rows: total={evaluation.total_rows} "
            f"completed={evaluation.completed_rows} "
            f"failed={evaluation.failed_rows}"
        ),
        "",
        "## Per-metric aggregate",
    ]

    # Group metrics by parent so the prompt mirrors the hierarchy. Any
    # aggregate row whose ``metric_id`` is missing from ``metric_meta``
    # is rendered as a leaf at the top-level list (handles renamed /
    # deleted parents).
    children_by_parent: Dict[str, List[CallImportMetricAggregate]] = {}
    top_level: List[CallImportMetricAggregate] = []
    for agg in aggregate:
        meta = metric_meta.get(agg.metric_id)
        parent_id = (
            str(meta.parent_metric_id)
            if meta is not None and getattr(meta, "parent_metric_id", None)
            else None
        )
        if parent_id:
            children_by_parent.setdefault(parent_id, []).append(agg)
        else:
            top_level.append(agg)

    def _format_metric_block(agg: CallImportMetricAggregate, indent: int) -> List[str]:
        prefix = "  " * indent + "- "
        bits: List[str] = [f"{prefix}{agg.metric_name} (n={agg.count}"]
        if agg.skipped_count:
            bits.append(f", skipped={agg.skipped_count}")
        if agg.error_count:
            bits.append(f", errors={agg.error_count}")
        bits.append(")")
        if agg.mean is not None:
            mean_s = f"{agg.mean:.2f}"
            stddev_s = f"{agg.stddev:.2f}" if agg.stddev is not None else "-"
            bits.append(f" | mean={mean_s} stddev={stddev_s}")
            if agg.min is not None and agg.max is not None:
                bits.append(f" range=[{agg.min:.2f}, {agg.max:.2f}]")
        if agg.value_counts:
            total = sum(v.count for v in agg.value_counts) or 1
            top = agg.value_counts[:3]
            shares = ", ".join(
                f'"{v.label}"={v.count}/{total}' for v in top
            )
            bits.append(f" | top={shares}")
        result = ["".join(bits)]
        rationales = rationale_samples.get(agg.metric_id, [])
        for r in rationales:
            result.append("  " * (indent + 1) + f"- rationale: {r}")
        return result

    for agg in top_level:
        lines.extend(_format_metric_block(agg, indent=0))
        meta = metric_meta.get(agg.metric_id)
        children = children_by_parent.get(str(meta.id), []) if meta else []
        for child in children:
            lines.extend(_format_metric_block(child, indent=1))

    lines.append("")
    lines.append(
        "Write the JSON object as instructed. Do not include "
        "preamble, code fences, or trailing commentary."
    )

    return [
        {"role": "system", "content": _INSIGHTS_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(lines)},
    ]


def _parse_insights_response(text: str) -> EvaluationTldrSummary:
    """Coerce the LLM response into ``narrative`` + ``patterns``.

    Matches the JSON-with-fallback pattern used by
    ``app.api.v1.routes.metrics._parse_metric_generation_response``: try
    ``json.loads`` first, then fall back to regex extraction of the
    first ``{...}`` block. Raises ``HTTPException`` with a 502 when the
    response can't be parsed at all.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        raise HTTPException(
            status_code=502, detail="LLM returned an empty insights response"
        )
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        import re

        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise HTTPException(
                status_code=502,
                detail="Could not parse LLM insights response as JSON",
            )
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError as e:
            raise HTTPException(
                status_code=502,
                detail=f"Could not parse LLM insights response: {e}",
            )

    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=502, detail="LLM insights JSON was not an object"
        )

    narrative = parsed.get("narrative")
    if not isinstance(narrative, str) or not narrative.strip():
        raise HTTPException(
            status_code=502,
            detail="LLM insights JSON missing 'narrative' string",
        )

    patterns_raw = parsed.get("patterns")
    if patterns_raw is None:
        patterns: List[str] = []
    elif isinstance(patterns_raw, list):
        patterns = [
            str(p).strip()
            for p in patterns_raw
            if isinstance(p, str) and p.strip()
        ]
    else:
        raise HTTPException(
            status_code=502,
            detail="LLM insights JSON 'patterns' must be a list of strings",
        )

    return EvaluationTldrSummary(
        narrative=narrative.strip(),
        patterns=patterns,
        generated_at=datetime.now(timezone.utc),
        generated_at_completed_rows=0,  # filled in by caller
        is_stale=False,
    )


@router.get(
    "/{eval_id}/insights",
    response_model=Optional[EvaluationTldrSummary],
    operation_id="getCallImportEvaluationInsights",
)
async def get_call_import_evaluation_insights(
    call_import_id: UUID,
    eval_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> Optional[EvaluationTldrSummary]:
    """Return the cached TLDR (or ``null``) without contacting the LLM.

    Used by the Visualizations tab on first paint so the empty-state
    CTA can show up before the user opts into generation.
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
    return _tldr_summary_payload(evaluation)


@router.post(
    "/{eval_id}/insights",
    response_model=EvaluationTldrSummary,
    operation_id="generateCallImportEvaluationInsights",
)
async def generate_call_import_evaluation_insights(
    call_import_id: UUID,
    eval_id: UUID,
    body: EvaluationInsightsRequest = Body(default_factory=EvaluationInsightsRequest),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> EvaluationTldrSummary:
    """Generate (or return-cached) the LLM TLDR for an evaluation run.

    Behavior:

    * ``body.regenerate=False`` and a cached summary at the current
      ``completed_rows`` watermark exists -> return it as-is.
    * ``body.regenerate=False`` and a stale cached summary exists
      (``generated_at_completed_rows < completed_rows``) -> return it
      with ``is_stale=True``; the UI prompts the user to regenerate.
    * Otherwise -> resolve provider+model (auto-detect when omitted),
      call the LLM, persist the new summary, return it.
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

    if not body.regenerate:
        cached = _tldr_summary_payload(evaluation)
        if cached is not None:
            return cached

    # Generation path. Reuse the existing aggregate computation so the
    # prompt sees identical numbers to the charts on the same page.
    eval_rows = (
        db.query(CallImportEvaluationRow)
        .filter(CallImportEvaluationRow.evaluation_id == eval_id)
        .all()
    )
    aggregate = _compute_metric_aggregates(db, evaluation, eval_rows)
    if not aggregate:
        raise HTTPException(
            status_code=400,
            detail=(
                "No metric data yet. Wait for at least one row to "
                "finish scoring before generating a summary."
            ),
        )

    # Pull every metric the aggregate references so we can map
    # parent->child relationships in the prompt.
    metric_ids: List[UUID] = []
    for agg in aggregate:
        try:
            metric_ids.append(UUID(agg.metric_id))
        except (TypeError, ValueError):
            continue
    metrics = _metrics_for_ids(db, organization_id, metric_ids)
    metric_meta: Dict[str, Metric] = {str(m.id): m for m in metrics}

    rationale_samples = _sample_rationales_per_metric(eval_rows)
    messages = _build_insights_messages(
        evaluation, aggregate, rationale_samples, metric_meta
    )

    # Imported lazily so the route module stays importable in tests
    # that stub out ``app.workers.tasks`` (which transitively imports
    # ``llm_service`` via the worker registry).
    from app.services.ai.llm_resolver import get_llm_provider_and_model
    from app.services.ai.llm_service import llm_service

    provider_enum, model_str = get_llm_provider_and_model(
        organization_id, db, body.provider, body.model
    )

    try:
        llm_result = llm_service.generate_response(
            messages=messages,
            llm_provider=provider_enum,
            llm_model=model_str,
            organization_id=organization_id,
            db=db,
            temperature=0.4,
            max_tokens=700,
        )
    except Exception as e:
        logger.error(f"[CallImportInsights] LLM call failed: {e}")
        raise HTTPException(
            status_code=502, detail=f"LLM call failed: {e}"
        )

    summary = _parse_insights_response(llm_result.get("text", ""))
    summary.generated_at_completed_rows = evaluation.completed_rows
    summary.provider = provider_enum.value
    summary.model = model_str
    summary.is_stale = False

    evaluation.tldr_summary = {
        "narrative": summary.narrative,
        "patterns": summary.patterns,
        "generated_at": summary.generated_at.isoformat(),
        "generated_at_completed_rows": summary.generated_at_completed_rows,
        "provider": summary.provider,
        "model": summary.model,
    }
    # ``JSON`` columns aren't auto-tracked when the same dict is mutated
    # in place; reassigning is the safest pattern, but we also flag the
    # attribute so SQLAlchemy schedules the UPDATE either way.
    flag_modified(evaluation, "tldr_summary")
    db.commit()
    db.refresh(evaluation)

    return summary


# ---------------------------------------------------------------------------
# Flow chart: turns per-row LLM-inferred ``sequence`` arrays into a
# directed graph of (label -> label) transitions across the whole run.
# Powers the aggregate Sankey-style React Flow chart on the evaluation
# overview; per-call flow charts are built client-side from the same
# ``sequence`` field on a single row's metric_scores entry.
# ---------------------------------------------------------------------------


_FLOW_TERMINAL_THRESHOLD = 0.2  # Mark as terminal when >=20% of sequences end here.
_FLOW_START_NODE_ID = "__START__"
_DISCOVERED_NODE_PREFIX = "disc:"


def _slug_label(value: Any) -> str:
    """Lowercase + whitespace-collapse + underscore-join.

    Used everywhere we need a stable key for a metric/label name —
    matching the same convention the worker uses when emitting
    ``sequence`` entries and discovered keys.
    """
    if value is None:
        return ""
    return "_".join(str(value).strip().lower().split())


def _resolve_alias(alias_map: Dict[str, str], key: str) -> str:
    """Walk the alias map until we hit a slug that doesn't redirect.

    The merge endpoint stores ``from_slug -> to_slug`` pairs. The delete
    endpoint stores ``from_slug -> ""`` (empty string sentinel) to mark
    a slug as tombstoned. Chains can accumulate when the user merges
    A→B and later merges B→C; this helper collapses them so callers
    always land on the final canonical slug.

    Returns:
      * the canonical slug if it still resolves to a real label,
      * an empty string if the slug has been tombstoned (callers MUST
        treat an empty result as "drop this entry entirely"),
      * the input ``key`` if it isn't aliased.

    Cycles are guarded by a hard step limit since the alias map is
    user-driven.
    """
    if not key:
        return ""
    if not alias_map:
        return key
    current = key
    seen: set[str] = set()
    for _ in range(16):
        if current in seen:
            return current
        seen.add(current)
        if current not in alias_map:
            return current
        nxt = alias_map[current]
        if nxt == current:
            return current
        if nxt == "":
            # Deletion sentinel — the user has explicitly retired this
            # slug. Propagate the empty string up so callers drop it.
            return ""
        current = nxt
    return current


# Reserved JSON key under which the worker stores top-level metric
# discoveries on each row's ``metric_scores`` dict. Mirrors the constant
# in ``app/workers/tasks/helpers/llm_evaluation.py`` — kept local here to
# avoid a worker import cycle from the routes module.
DISCOVERED_METRICS_KEY = "__discovered_metrics__"

# Allowed values for an LLM-suggested top-level metric type. Kept in
# sync with ``DiscoveredMetricSuggestedType`` in
# ``app/models/schemas.py``.
_DISCOVERED_METRIC_TYPES = ("boolean", "rating", "category")


def normalize_scores_with_aliases(
    metric_scores: Dict[str, Any],
    evaluation: CallImportEvaluation,
    db: Session,
    organization_id: UUID,
) -> Dict[str, Any]:
    """Rewrite per-row ``metric_scores`` to honor merges + promotions.

    Called by the worker right after ``evaluate_with_llm`` returns so
    every row that finishes AFTER a user has merged or promoted a
    discovered label persists data already reflecting that decision.
    Without this hook, a worker holding a stale prompt could re-emit a
    ``from_key`` slug long after the user merged it away.

    For every parent entry (``selection_mode != null`` and a
    ``discovered_labels`` / ``sequence`` field) we:

      * resolve discovered slugs through the evaluation's
        ``discovered_label_aliases`` map (transitively),
      * drop any discovered_labels entry whose canonical slug now
        matches a real promoted child of the parent (merging them out
        of the panel for free), and
      * collapse adjacent duplicate sequence entries that result.

    Returns ``metric_scores`` (mutated in place) for chaining.
    """
    if not isinstance(metric_scores, dict):
        return metric_scores

    aliases_top = (
        evaluation.discovered_label_aliases
        if isinstance(evaluation.discovered_label_aliases, dict)
        else {}
    )

    # Identify the parent entries inside metric_scores. They're the
    # dicts that carry a ``selection_mode`` key (set by the LLM
    # hierarchy parser) and either a ``sequence`` or a
    # ``discovered_labels`` list.
    for key, entry in list(metric_scores.items()):
        if not isinstance(entry, dict):
            continue
        if entry.get("type") != "category" and not entry.get("selection_mode"):
            continue
        try:
            parent_uuid = UUID(str(key))
        except (TypeError, ValueError):
            continue

        alias_map = {}
        sub = aliases_top.get(str(parent_uuid))
        if isinstance(sub, dict):
            alias_map = {
                str(k): str(v)
                for k, v in sub.items()
                if isinstance(k, str) and isinstance(v, str)
            }
        promoted = _promoted_child_slugs(db, parent_uuid, organization_id)

        # Rewrite discovered_labels: alias-resolve keys, drop duplicates
        # post-resolution, and drop entries that have been promoted.
        discovered = entry.get("discovered_labels")
        if isinstance(discovered, list):
            kept_disc: List[Dict[str, Any]] = []
            seen: set[str] = set()
            for d in discovered:
                if not isinstance(d, dict):
                    continue
                slug = _slug_label(d.get("key") or d.get("name"))
                slug = _resolve_alias(alias_map, slug)
                if not slug or slug in promoted or slug in seen:
                    continue
                seen.add(slug)
                new_entry = dict(d)
                new_entry["key"] = slug
                kept_disc.append(new_entry)
            entry["discovered_labels"] = kept_disc

        # Rewrite sequence: alias-resolve every entry; collapse adjacent
        # duplicates that result. We DON'T drop slugs that match
        # promoted children — the promoted child slug is still a valid
        # sequence entry; the flow chart will resolve it to the real
        # child node.
        seq = entry.get("sequence")
        if isinstance(seq, list):
            new_seq: List[str] = []
            last: Optional[str] = None
            for item in seq:
                if not isinstance(item, str):
                    continue
                slug = _resolve_alias(alias_map, _slug_label(item))
                if not slug or slug == last:
                    continue
                new_seq.append(slug)
                last = slug
            entry["sequence"] = new_seq

    # Top-level metric discoveries live alongside the parent entries
    # under the reserved ``DISCOVERED_METRICS_KEY`` slot. Apply the
    # flat evaluation-level alias/tombstone map + suppress slugs that
    # already correspond to a real top-level Metric so workers that
    # finish AFTER the user has merged / deleted / promoted can't
    # resurrect a retired candidate.
    discovered_metrics_payload = metric_scores.get(DISCOVERED_METRICS_KEY)
    if isinstance(discovered_metrics_payload, list):
        flat_alias_map = (
            evaluation.discovered_metric_aliases
            if isinstance(evaluation.discovered_metric_aliases, dict)
            else {}
        )
        promoted_metric_slugs = _promoted_top_level_metric_slugs(
            db, organization_id
        )
        kept_metrics: List[Dict[str, Any]] = []
        seen_metrics: set[str] = set()
        for d in discovered_metrics_payload:
            if not isinstance(d, dict):
                continue
            slug = _slug_label(d.get("key") or d.get("name"))
            slug = _resolve_alias(flat_alias_map, slug)
            if (
                not slug
                or slug in promoted_metric_slugs
                or slug in seen_metrics
            ):
                continue
            seen_metrics.add(slug)
            new_entry = dict(d)
            new_entry["key"] = slug
            kept_metrics.append(new_entry)
        if kept_metrics:
            metric_scores[DISCOVERED_METRICS_KEY] = kept_metrics
        else:
            # No survivors — drop the empty array so empty-discovery rows
            # keep their pre-feature payload shape.
            metric_scores.pop(DISCOVERED_METRICS_KEY, None)

    return metric_scores


def _alias_map_for_parent(
    evaluation: CallImportEvaluation, parent_metric_id: UUID
) -> Dict[str, str]:
    """Pull ``{from_slug: to_slug}`` for one parent out of the eval's blob.

    Stored shape on the evaluation row is
    ``{parent_id_str: {from_slug: to_slug, ...}}``. Returns an empty
    dict for parents that have never had a merge applied.
    """
    raw = getattr(evaluation, "discovered_label_aliases", None)
    if not isinstance(raw, dict):
        return {}
    submap = raw.get(str(parent_metric_id))
    if not isinstance(submap, dict):
        return {}
    return {
        str(k): str(v)
        for k, v in submap.items()
        if isinstance(k, str) and isinstance(v, str)
    }


def _promoted_child_slugs(
    db: Session, parent_metric_id: UUID, organization_id: UUID
) -> set[str]:
    """Slugs of every real child currently sitting under the parent.

    The Discovered Labels panel hides any candidate whose slug already
    matches a real child — that covers both freshly-promoted candidates
    and legacy children the LLM happened to re-discover. We pull from
    the live ``metrics`` table rather than the eval's
    ``selected_metric_groups`` snapshot so newly-promoted children take
    effect immediately, even on evaluations that ran before the
    promotion.
    """
    children = (
        db.query(Metric.name)
        .filter(
            Metric.parent_metric_id == parent_metric_id,
            Metric.organization_id == organization_id,
        )
        .all()
    )
    out: set[str] = set()
    for (name,) in children:
        slug = _slug_label(name)
        if slug:
            out.add(slug)
    return out


def _promoted_top_level_metric_slugs(
    db: Session, organization_id: UUID
) -> set[str]:
    """Slugs of every top-level (non-child) Metric in the organization.

    Used to suppress discovered-metric candidates whose slug already
    matches a real standalone metric. We intentionally include both
    standalone metrics AND parent category metrics — a top-level
    discovery that collides with either name is a duplicate by
    definition.
    """
    rows = (
        db.query(Metric.name)
        .filter(
            Metric.organization_id == organization_id,
            Metric.parent_metric_id.is_(None),
        )
        .all()
    )
    out: set[str] = set()
    for (name,) in rows:
        slug = _slug_label(name)
        if slug:
            out.add(slug)
    return out


def _get_running_discovered_labels(
    db: Session,
    eval_id: UUID,
    parent_metric_id: UUID,
    organization_id: Optional[UUID] = None,
    alias_map: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Slug-deduped view of every discovered label seen in this eval so far.

    Walks each ``call_import_evaluation_rows`` row's
    ``metric_scores[parent_id]["discovered_labels"]`` and folds entries
    that share the same slug. Returns a list ordered by descending
    count and stable on label key, shaped like::

        [{"key": "customer_on_hold", "name": "Customer put on hold",
          "description": "...", "sample_rationale": "...", "count": 12}]

    Powers two callers:
      * The worker prompt builder ("REUSE the existing key if it fits")
        — invoked just before each row's LLM call to feed the model the
        running list of previously-discovered labels in this evaluation.
      * The ``/discovered-labels`` API surface used by the frontend
        Discovered Labels panel to render candidates with counts +
        sample rationales.

    Non-completed rows are skipped: an in-flight row's discoveries are
    not yet reliable (the row could fail and never produce final
    metric_scores). We accept the tradeoff that rows running
    concurrently won't see each other's labels — slug-collision dedup
    catches identical re-inventions, and near-paraphrases surface in
    the UI panel where the user can manually merge.
    """

    parent_id_str = str(parent_metric_id)
    rows = (
        db.query(CallImportEvaluationRow.metric_scores)
        .filter(
            CallImportEvaluationRow.evaluation_id == eval_id,
            CallImportEvaluationRow.status
            == CallImportRowStatus.COMPLETED.value,
        )
        .all()
    )

    # Suppress slugs that have either:
    #  * been promoted to a real child of the parent (so the panel doesn't
    #    keep nagging the user about a candidate they've already
    #    accepted), or
    #  * been merged INTO another slug (the "from" side of a merge) —
    #    those occurrences fold into the canonical target instead.
    promoted_slugs: set[str] = set()
    if organization_id is not None:
        promoted_slugs = _promoted_child_slugs(
            db, parent_metric_id, organization_id
        )
    aliases = alias_map or {}

    by_key: Dict[str, Dict[str, Any]] = {}
    for (scores,) in rows:
        if not isinstance(scores, dict):
            continue
        parent_entry = scores.get(parent_id_str)
        if not isinstance(parent_entry, dict):
            continue
        discovered = parent_entry.get("discovered_labels")
        if not isinstance(discovered, list):
            continue
        for entry in discovered:
            if not isinstance(entry, dict):
                continue
            raw_key = entry.get("key") or entry.get("name")
            key = _slug_label(raw_key)
            if not key:
                continue
            # Apply user merges + deletions first, THEN drop anything
            # that ended up on a real child slug. Order matters: a
            # candidate that was merged into a slug which has since
            # been promoted should disappear, not show up at the
            # canonical slug. An empty resolved key means the slug was
            # tombstoned via the delete endpoint.
            key = _resolve_alias(aliases, key)
            if not key or key in promoted_slugs:
                continue
            name = (entry.get("name") or "").strip() or key.replace("_", " ")
            description = (entry.get("description") or "").strip() or None
            sample = (entry.get("rationale") or "").strip() or None

            existing = by_key.get(key)
            if existing is None:
                # Track up to N=3 distinct rationales per candidate so
                # the Promote-to-child flow can pre-fill the new
                # sub-metric's rubric with concrete LLM examples
                # without the user copy-pasting from the row table.
                # ``sample_rationale`` is preserved for back-compat
                # with older clients; ``examples`` is the new field.
                examples = [sample] if sample else []
                by_key[key] = {
                    "key": key,
                    "name": name,
                    "description": description,
                    "sample_rationale": sample,
                    "examples": examples,
                    "count": 1,
                }
                continue

            existing["count"] += 1
            if not existing["description"] and description:
                existing["description"] = description
            if not existing["sample_rationale"] and sample:
                existing["sample_rationale"] = sample
            # Append distinct rationales (case-insensitive trim) up
            # to a small cap. Headroom is intentionally one above
            # what the UI surfaces (2) so we have a backup when the
            # first rationale is unhelpful.
            if sample:
                ex_list: List[str] = existing.setdefault("examples", [])
                if len(ex_list) < 3 and not any(
                    s.strip().lower() == sample.strip().lower() for s in ex_list
                ):
                    ex_list.append(sample)

    return sorted(
        by_key.values(),
        key=lambda item: (-item["count"], item["key"]),
    )


def _get_running_discovered_metrics(
    db: Session,
    eval_id: UUID,
    organization_id: Optional[UUID] = None,
    alias_map: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Slug-deduped view of every discovered top-level metric in this eval.

    Mirrors :func:`_get_running_discovered_labels` but is keyed at the
    evaluation level (no ``parent_metric_id``). Walks each completed
    row's ``metric_scores[DISCOVERED_METRICS_KEY]`` list, folds entries
    that share the same slug (post-alias resolution), and suppresses
    slugs that already correspond to a real top-level :class:`Metric`
    in the organization.

    Each returned entry is shaped::

        {"key": "customer_satisfaction",
         "name": "Customer Satisfaction",
         "description": "...",
         "suggested_type": "boolean" | "rating" | "category",
         "sample_rationale": "...",
         "examples": ["..."],
         "count": 12}
    """

    rows = (
        db.query(CallImportEvaluationRow.metric_scores)
        .filter(
            CallImportEvaluationRow.evaluation_id == eval_id,
            CallImportEvaluationRow.status
            == CallImportRowStatus.COMPLETED.value,
        )
        .all()
    )

    promoted_slugs: set[str] = set()
    if organization_id is not None:
        promoted_slugs = _promoted_top_level_metric_slugs(
            db, organization_id
        )
    aliases = alias_map or {}

    by_key: Dict[str, Dict[str, Any]] = {}
    for (scores,) in rows:
        if not isinstance(scores, dict):
            continue
        discovered = scores.get(DISCOVERED_METRICS_KEY)
        if not isinstance(discovered, list):
            continue
        for entry in discovered:
            if not isinstance(entry, dict):
                continue
            raw_key = entry.get("key") or entry.get("name")
            key = _slug_label(raw_key)
            if not key:
                continue
            # Apply user merges + deletions first, THEN drop anything
            # that ended up on an already-existing top-level metric
            # slug. Empty resolved key = tombstoned.
            key = _resolve_alias(aliases, key)
            if not key or key in promoted_slugs:
                continue
            name = (entry.get("name") or "").strip() or key.replace(
                "_", " "
            )
            description = (entry.get("description") or "").strip() or None
            sample = (entry.get("rationale") or "").strip() or None
            raw_type = str(entry.get("suggested_type") or "").strip().lower()
            if raw_type not in _DISCOVERED_METRIC_TYPES:
                raw_type = "boolean"

            existing = by_key.get(key)
            if existing is None:
                examples = [sample] if sample else []
                by_key[key] = {
                    "key": key,
                    "name": name,
                    "description": description,
                    "suggested_type": raw_type,
                    "sample_rationale": sample,
                    "examples": examples,
                    "count": 1,
                }
                continue

            existing["count"] += 1
            if not existing["description"] and description:
                existing["description"] = description
            if not existing["sample_rationale"] and sample:
                existing["sample_rationale"] = sample
            # Keep the most-frequently-suggested type. We don't track
            # per-type frequency yet; defer to the first non-default
            # type encountered when the existing entry has the default.
            if existing.get("suggested_type") == "boolean" and raw_type != "boolean":
                existing["suggested_type"] = raw_type
            if sample:
                ex_list: List[str] = existing.setdefault("examples", [])
                if len(ex_list) < 3 and not any(
                    s.strip().lower() == sample.strip().lower() for s in ex_list
                ):
                    ex_list.append(sample)

    return sorted(
        by_key.values(),
        key=lambda item: (-item["count"], item["key"]),
    )


def _build_flow_graph(
    eval_rows: List[CallImportEvaluationRow],
    parent_metric: Metric,
    children: List[Metric],
    alias_map: Optional[Dict[str, str]] = None,
    extra_children: Optional[List[Metric]] = None,
) -> MetricFlowResponse:
    """Walk per-row ``sequence`` arrays and produce aggregate nodes/edges.

    A synthetic ``START`` node is prepended to every sequence so the
    diagram has a single origin. Children that never appear in any
    sequence are still emitted as nodes (count=0) so the UI can render
    them in the legend.

    ``alias_map`` lets callers fold merged-out discovered slugs into
    their canonical target before building the graph; ``extra_children``
    are children of the parent that aren't in the legend list (e.g.
    children promoted *after* the evaluation was created and therefore
    missing from ``selected_metric_groups``) but should still resolve in
    sequences so the slug doesn't get redrawn as a discovered candidate.
    """
    parent_id_str = str(parent_metric.id)
    aliases = alias_map or {}
    # Build a fast lookup keyed by both the lower_snake child key (what the
    # LLM emits in ``sequence``) and the child UUID (what some clients may
    # store) so legacy / drifted payloads still resolve.
    child_lookup: Dict[str, Metric] = {}
    for child in children:
        slug = _slug_label(child.name)
        child_lookup[slug] = child
        child_lookup[str(child.id)] = child
    # ``extra_children`` are resolved-only — they shouldn't add legend
    # nodes (those come from the explicit ``children`` argument), but
    # they need to be in ``child_lookup`` so a sequence step that
    # matches a freshly-promoted child resolves to the real child UUID
    # instead of falling through to ``discovered_lookup`` and rendering
    # as a "discovered" node.
    if extra_children:
        for child in extra_children:
            slug = _slug_label(child.name)
            if slug and slug not in child_lookup:
                child_lookup[slug] = child
            cid = str(child.id)
            child_lookup.setdefault(cid, child)

    # Discovered labels: walk every row's discovered_labels first so we
    # know which discovered slugs are valid before resolving sequences.
    # Discovered nodes get a ``disc:`` prefixed id so they can't collide
    # with real child UUIDs in the node/edge graph. We apply
    # ``alias_map`` first so merged-out source slugs fold into their
    # canonical target — preserving the user's "merge" intent on still-
    # in-flight rows whose JSON wasn't rewritten by the merge endpoint.
    discovered_lookup: Dict[str, Dict[str, Any]] = {}
    for row in eval_rows:
        scores = (
            row.metric_scores if isinstance(row.metric_scores, dict) else {}
        )
        parent_entry = scores.get(parent_id_str)
        if not isinstance(parent_entry, dict):
            continue
        raw_discovered = parent_entry.get("discovered_labels")
        if not isinstance(raw_discovered, list):
            continue
        for entry in raw_discovered:
            if not isinstance(entry, dict):
                continue
            slug = _slug_label(entry.get("key") or entry.get("name"))
            slug = _resolve_alias(aliases, slug)
            if not slug or slug in child_lookup:
                continue
            name = (entry.get("name") or "").strip() or slug.replace("_", " ")
            existing = discovered_lookup.get(slug)
            if existing is None:
                discovered_lookup[slug] = {
                    "id": f"{_DISCOVERED_NODE_PREFIX}{slug}",
                    "name": name,
                }

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
        last_resolved: Optional[str] = None
        for item in raw_sequence:
            if not isinstance(item, str):
                continue
            normalized = _resolve_alias(aliases, _slug_label(item))
            child = child_lookup.get(normalized) or child_lookup.get(item)
            if child is not None:
                cid = str(child.id)
                # Adjacent dedupe AFTER alias resolution so two
                # different raw slugs that fold to the same target
                # don't draw a self-edge through the chart.
                if cid == last_resolved:
                    continue
                resolved_ids.append(cid)
                last_resolved = cid
                continue
            disc = discovered_lookup.get(normalized)
            if disc is not None:
                if disc["id"] == last_resolved:
                    continue
                resolved_ids.append(disc["id"])
                last_resolved = disc["id"]

        if not resolved_ids:
            continue

        rows_with_sequence += 1
        for nid in resolved_ids:
            node_counts[nid] = node_counts.get(nid, 0) + 1

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

    def _emit_child_node(child: Metric) -> None:
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

    emitted_child_ids: set[str] = set()
    for child in children:
        cid = str(child.id)
        if cid in emitted_child_ids:
            continue
        emitted_child_ids.add(cid)
        _emit_child_node(child)
    # Extra children (promoted after the eval was created) only get
    # legend nodes if they actually appear in the data — otherwise we'd
    # pollute the diagram with every standalone promotion the user has
    # ever made under this parent.
    if extra_children:
        for child in extra_children:
            cid = str(child.id)
            if cid in emitted_child_ids:
                continue
            if node_counts.get(cid, 0) == 0:
                continue
            emitted_child_ids.add(cid)
            _emit_child_node(child)
    # Append discovered nodes after the real children so legend ordering
    # keeps user-defined labels first.
    for slug, info in discovered_lookup.items():
        nid = info["id"]
        count = node_counts.get(nid, 0)
        terminal_count = terminal_counts.get(nid, 0)
        is_terminal = False
        if rows_with_sequence > 0:
            is_terminal = (
                terminal_count / rows_with_sequence
            ) >= _FLOW_TERMINAL_THRESHOLD
        nodes.append(
            MetricFlowNode(
                id=nid,
                label=info["name"],
                count=count,
                is_terminal=is_terminal,
                is_discovered=True,
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

    # Children promoted AFTER this evaluation was created aren't in
    # ``selected_metric_groups`` but their slugs still appear in already-
    # scored rows' sequences. Pass them as ``extra_children`` so those
    # sequence entries resolve against the real (now promoted) child
    # instead of being redrawn as discovered candidates.
    extra_children: List[Metric] = []
    if children:
        existing_ids = {child.id for child in children}
        all_children = (
            db.query(Metric)
            .filter(
                Metric.organization_id == organization_id,
                Metric.parent_metric_id == parent.id,
            )
            .all()
        )
        extra_children = [c for c in all_children if c.id not in existing_ids]

    eval_rows = (
        db.query(CallImportEvaluationRow)
        .filter(CallImportEvaluationRow.evaluation_id == eval_id)
        .all()
    )

    alias_map = _alias_map_for_parent(evaluation, parent.id)
    return _build_flow_graph(
        eval_rows,
        parent,
        children,
        alias_map=alias_map,
        extra_children=extra_children,
    )


@router.get(
    "/{eval_id}/discovered-labels",
    response_model=DiscoveredLabelsResponse,
    operation_id="getCallImportEvaluationDiscoveredLabels",
)
async def get_call_import_evaluation_discovered_labels(
    call_import_id: UUID,
    eval_id: UUID,
    parent_metric_id: UUID = Query(
        ...,
        description=(
            "Parent (category) metric whose LLM-discovered candidate "
            "sub-labels should be aggregated across rows."
        ),
    ),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> DiscoveredLabelsResponse:
    """Aggregate candidate sub-labels the LLM discovered during this eval.

    Only meaningful for parents with ``allow_discovery=true``; for other
    parents we just return an empty ``items`` list rather than 400-ing
    so the frontend can call the endpoint unconditionally for every
    parent on the Flow tab without branching.
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

    alias_map = _alias_map_for_parent(evaluation, parent_metric_id)
    items_raw = _get_running_discovered_labels(
        db,
        eval_id,
        parent_metric_id,
        organization_id=organization_id,
        alias_map=alias_map,
    )
    items = [DiscoveredLabelItem(**item) for item in items_raw]
    return DiscoveredLabelsResponse(
        parent_metric_id=str(parent.id), items=items
    )


@router.post(
    "/{eval_id}/discovered-labels/merge",
    response_model=DiscoveredLabelsResponse,
    operation_id="mergeCallImportEvaluationDiscoveredLabels",
)
async def merge_call_import_evaluation_discovered_labels(
    call_import_id: UUID,
    eval_id: UUID,
    body: DiscoveredLabelMergeRequest,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> DiscoveredLabelsResponse:
    """Rewrite every row's ``discovered_labels`` entry from from_key -> to_key.

    Idempotent — re-merging the same pair is a no-op. Discovered slugs
    inside per-row ``sequence`` arrays are also rewritten so the flow
    chart stays consistent with the panel. When a row already has
    ``to_key`` and we're merging ``from_key`` into it, we drop the
    ``from_key`` entry instead of producing two entries with the same
    slug.
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
            Metric.id == body.parent_metric_id,
            Metric.organization_id == organization_id,
        )
        .first()
    )
    if not parent:
        raise HTTPException(
            status_code=404,
            detail="Parent metric not found in this organization.",
        )

    from_key = _slug_label(body.from_key)
    to_key = _slug_label(body.to_key)
    if not from_key or not to_key:
        raise HTTPException(
            status_code=400,
            detail="from_key and to_key must be non-empty slugs.",
        )
    if from_key == to_key:
        # No-op; just return the current aggregate so the client can
        # refresh its view.
        alias_map_existing = _alias_map_for_parent(evaluation, parent.id)
        items_raw = _get_running_discovered_labels(
            db,
            eval_id,
            body.parent_metric_id,
            organization_id=organization_id,
            alias_map=alias_map_existing,
        )
        return DiscoveredLabelsResponse(
            parent_metric_id=str(parent.id),
            items=[DiscoveredLabelItem(**item) for item in items_raw],
        )

    parent_id_str = str(parent.id)
    rows = (
        db.query(CallImportEvaluationRow)
        .filter(CallImportEvaluationRow.evaluation_id == eval_id)
        .all()
    )

    for row in rows:
        scores = (
            row.metric_scores
            if isinstance(row.metric_scores, dict)
            else None
        )
        if not scores:
            continue
        parent_entry = scores.get(parent_id_str)
        if not isinstance(parent_entry, dict):
            continue

        mutated = False
        # 1. Rewrite the discovered_labels list. If the row already has
        # an entry for to_key we keep that (it carries the user-chosen
        # name + sample rationale) and just drop the from_key entry.
        discovered = parent_entry.get("discovered_labels")
        if isinstance(discovered, list):
            kept: List[Dict[str, Any]] = []
            existing_to = next(
                (
                    e
                    for e in discovered
                    if isinstance(e, dict)
                    and _slug_label(e.get("key") or e.get("name")) == to_key
                ),
                None,
            )
            for entry in discovered:
                if not isinstance(entry, dict):
                    kept.append(entry)
                    continue
                key = _slug_label(entry.get("key") or entry.get("name"))
                if key == from_key:
                    if existing_to is not None:
                        mutated = True
                        continue
                    new_entry = dict(entry)
                    new_entry["key"] = to_key
                    kept.append(new_entry)
                    mutated = True
                else:
                    kept.append(entry)
            if mutated:
                parent_entry["discovered_labels"] = kept

        # 2. Rewrite any discovered slugs inside the sequence array so
        # the flow chart stays consistent. Dedupe so we don't end up
        # with adjacent identical entries.
        seq = parent_entry.get("sequence")
        if isinstance(seq, list):
            new_seq: List[str] = []
            seq_changed = False
            last_added: Optional[str] = None
            for item in seq:
                if isinstance(item, str) and _slug_label(item) == from_key:
                    seq_changed = True
                    if last_added == to_key:
                        continue
                    new_seq.append(to_key)
                    last_added = to_key
                else:
                    new_seq.append(item)
                    last_added = (
                        _slug_label(item) if isinstance(item, str) else None
                    )
            if seq_changed:
                parent_entry["sequence"] = new_seq
                mutated = True

        if mutated:
            # ``JSON`` columns aren't auto-tracked when the same dict is
            # mutated in place — ``scores`` IS ``row.metric_scores``, so
            # the in-place edits above already updated SQLAlchemy's
            # cached "committed" snapshot to the post-edit dict. Without
            # ``flag_modified`` the subsequent ``dict(scores)`` reassign
            # compares equal to that snapshot and SQLAlchemy skips the
            # UPDATE, leaving the per-row payload stale on disk.
            row.metric_scores = dict(scores)
            flag_modified(row, "metric_scores")

    # Persist the merge at the evaluation level too. This is what makes
    # the merge survive future scoring: rows that finish AFTER this
    # call (e.g. retries, in-flight workers) will go through the
    # alias map in the API surface even if the per-row JSON they
    # write still mentions ``from_key``. We chain through any existing
    # alias so merging A→B and then B→C resolves A→C in the panel.
    raw_aliases = (
        evaluation.discovered_label_aliases
        if isinstance(evaluation.discovered_label_aliases, dict)
        else {}
    )
    aliases_top = dict(raw_aliases)
    parent_aliases = dict(aliases_top.get(parent_id_str) or {})
    # Resolve transitively: if to_key itself was previously merged into
    # something else, point from_key at the canonical end-of-chain.
    canonical_to = _resolve_alias(parent_aliases, to_key)
    parent_aliases[from_key] = canonical_to
    # Re-target any earlier aliases that pointed AT from_key — without
    # this, A→B and then B→C would leave A still pointing to B (now a
    # broken pointer because B is gone). Rewriting them keeps the
    # alias map self-consistent.
    for k, v in list(parent_aliases.items()):
        if v == from_key:
            parent_aliases[k] = canonical_to
    aliases_top[parent_id_str] = parent_aliases
    evaluation.discovered_label_aliases = aliases_top

    db.commit()

    alias_map_after = _alias_map_for_parent(evaluation, parent.id)
    items_raw = _get_running_discovered_labels(
        db,
        eval_id,
        body.parent_metric_id,
        organization_id=organization_id,
        alias_map=alias_map_after,
    )
    return DiscoveredLabelsResponse(
        parent_metric_id=str(parent.id),
        items=[DiscoveredLabelItem(**item) for item in items_raw],
    )


@router.post(
    "/{eval_id}/discovered-labels/delete",
    response_model=DiscoveredLabelsResponse,
    operation_id="deleteCallImportEvaluationDiscoveredLabel",
)
async def delete_call_import_evaluation_discovered_label(
    call_import_id: UUID,
    eval_id: UUID,
    body: DiscoveredLabelDeleteRequest,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> DiscoveredLabelsResponse:
    """Tombstone a single LLM-discovered candidate for this evaluation.

    Symmetric with the merge endpoint, but instead of redirecting the
    slug at another candidate we mark it as deleted. After this call:

      * the slug is stripped from every row's
        ``metric_scores[parent].discovered_labels`` list, and from
        every row's ``sequence`` array (so the flow chart no longer
        draws a node for it);
      * the slug is recorded in
        ``evaluation.discovered_label_aliases[parent][slug] = ""``
        so any worker that finishes a row AFTER this call (e.g. a row
        still in flight when the user clicked Delete) silently drops
        the slug instead of resurrecting it.

    Idempotent: deleting an already-deleted slug is a no-op.
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
            Metric.id == body.parent_metric_id,
            Metric.organization_id == organization_id,
        )
        .first()
    )
    if not parent:
        raise HTTPException(
            status_code=404,
            detail="Parent metric not found in this organization.",
        )

    target_key = _slug_label(body.key)
    if not target_key:
        raise HTTPException(
            status_code=400,
            detail="key must be a non-empty slug.",
        )

    parent_id_str = str(parent.id)
    rows = (
        db.query(CallImportEvaluationRow)
        .filter(CallImportEvaluationRow.evaluation_id == eval_id)
        .all()
    )

    for row in rows:
        scores = (
            row.metric_scores
            if isinstance(row.metric_scores, dict)
            else None
        )
        if not scores:
            continue
        parent_entry = scores.get(parent_id_str)
        if not isinstance(parent_entry, dict):
            continue

        mutated = False

        # 1. Strip the slug from discovered_labels.
        discovered = parent_entry.get("discovered_labels")
        if isinstance(discovered, list):
            kept = [
                e
                for e in discovered
                if not (
                    isinstance(e, dict)
                    and _slug_label(e.get("key") or e.get("name"))
                    == target_key
                )
            ]
            if len(kept) != len(discovered):
                parent_entry["discovered_labels"] = kept
                mutated = True

        # 2. Strip the slug from the sequence array, collapsing adjacent
        # duplicates that the deletion exposes.
        seq = parent_entry.get("sequence")
        if isinstance(seq, list):
            new_seq: List[str] = []
            seq_changed = False
            last_added: Optional[str] = None
            for item in seq:
                if isinstance(item, str) and _slug_label(item) == target_key:
                    seq_changed = True
                    continue
                if isinstance(item, str):
                    norm = _slug_label(item)
                    if norm == last_added:
                        seq_changed = True
                        continue
                    last_added = norm
                new_seq.append(item)
            if seq_changed:
                parent_entry["sequence"] = new_seq
                mutated = True

        if mutated:
            # See merge endpoint above: in-place edits to ``scores`` /
            # ``parent_entry`` already mutated SQLAlchemy's committed
            # snapshot, so the reassign alone wouldn't trigger an
            # UPDATE. Flagging the column forces it.
            row.metric_scores = dict(scores)
            flag_modified(row, "metric_scores")

    # 3. Persist the tombstone on the evaluation so workers that finish
    # later don't re-surface the deleted slug. We also retarget any
    # existing aliases whose ``to_key`` was the deleted slug — without
    # this, a previous merge that pointed at this slug would leave a
    # dangling pointer.
    raw_aliases = (
        evaluation.discovered_label_aliases
        if isinstance(evaluation.discovered_label_aliases, dict)
        else {}
    )
    aliases_top = dict(raw_aliases)
    parent_aliases = dict(aliases_top.get(parent_id_str) or {})
    parent_aliases[target_key] = ""  # deletion sentinel
    for k, v in list(parent_aliases.items()):
        if v == target_key:
            parent_aliases[k] = ""
    aliases_top[parent_id_str] = parent_aliases
    evaluation.discovered_label_aliases = aliases_top

    db.commit()

    alias_map_after = _alias_map_for_parent(evaluation, parent.id)
    items_raw = _get_running_discovered_labels(
        db,
        eval_id,
        body.parent_metric_id,
        organization_id=organization_id,
        alias_map=alias_map_after,
    )
    return DiscoveredLabelsResponse(
        parent_metric_id=str(parent.id),
        items=[DiscoveredLabelItem(**item) for item in items_raw],
    )


# ---------------------------------------------------------------------------
# Discovered TOP-LEVEL METRICS (per-evaluation discovery)
#
# These endpoints are the parallel of the discovered-labels trio above but
# scoped to the evaluation as a whole instead of to a parent metric. They
# all live under ``/{eval_id}/discovered-metrics`` and operate on the
# reserved ``DISCOVERED_METRICS_KEY`` slot of each per-row
# ``metric_scores`` plus the flat ``CallImportEvaluation.discovered_metric_aliases``
# map (no parent-id nesting).
# ---------------------------------------------------------------------------


def _flat_metric_aliases(
    evaluation: CallImportEvaluation,
) -> Dict[str, str]:
    """Pull the flat ``{from_slug: to_slug}`` map for an evaluation."""
    raw = getattr(evaluation, "discovered_metric_aliases", None)
    if not isinstance(raw, dict):
        return {}
    return {
        str(k): str(v)
        for k, v in raw.items()
        if isinstance(k, str) and isinstance(v, str)
    }


@router.get(
    "/{eval_id}/discovered-metrics",
    response_model=DiscoveredMetricsResponse,
    operation_id="getCallImportEvaluationDiscoveredMetrics",
)
async def get_call_import_evaluation_discovered_metrics(
    call_import_id: UUID,
    eval_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> DiscoveredMetricsResponse:
    """Aggregate top-level metric candidates the LLM discovered during this eval.

    Returns an empty ``items`` list when the evaluation did not opt
    into top-level metric discovery; this keeps the frontend able to
    call the endpoint unconditionally without branching on the
    evaluation's ``discover_new_metrics`` flag.
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

    if not bool(getattr(evaluation, "discover_new_metrics", False)):
        return DiscoveredMetricsResponse(evaluation_id=evaluation.id, items=[])

    items_raw = _get_running_discovered_metrics(
        db,
        eval_id,
        organization_id=organization_id,
        alias_map=_flat_metric_aliases(evaluation),
    )
    return DiscoveredMetricsResponse(
        evaluation_id=evaluation.id,
        items=[DiscoveredMetricItem(**item) for item in items_raw],
    )


@router.post(
    "/{eval_id}/discovered-metrics/merge",
    response_model=DiscoveredMetricsResponse,
    operation_id="mergeCallImportEvaluationDiscoveredMetrics",
)
async def merge_call_import_evaluation_discovered_metrics(
    call_import_id: UUID,
    eval_id: UUID,
    body: DiscoveredMetricMergeRequest,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> DiscoveredMetricsResponse:
    """Rewrite every row's ``__discovered_metrics__`` entry from→to.

    Mirrors the discovered-labels merge endpoint but operates on the
    flat top-level metric list. Idempotent — re-merging is a no-op.
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

    from_key = _slug_label(body.from_key)
    to_key = _slug_label(body.to_key)
    if not from_key or not to_key:
        raise HTTPException(
            status_code=400,
            detail="from_key and to_key must be non-empty slugs.",
        )
    if from_key == to_key:
        items_raw = _get_running_discovered_metrics(
            db,
            eval_id,
            organization_id=organization_id,
            alias_map=_flat_metric_aliases(evaluation),
        )
        return DiscoveredMetricsResponse(
            evaluation_id=evaluation.id,
            items=[DiscoveredMetricItem(**item) for item in items_raw],
        )

    rows = (
        db.query(CallImportEvaluationRow)
        .filter(CallImportEvaluationRow.evaluation_id == eval_id)
        .all()
    )

    for row in rows:
        scores = (
            row.metric_scores
            if isinstance(row.metric_scores, dict)
            else None
        )
        if not scores:
            continue
        discovered = scores.get(DISCOVERED_METRICS_KEY)
        if not isinstance(discovered, list):
            continue

        kept: List[Dict[str, Any]] = []
        mutated = False
        existing_to = next(
            (
                e
                for e in discovered
                if isinstance(e, dict)
                and _slug_label(e.get("key") or e.get("name")) == to_key
            ),
            None,
        )
        for entry in discovered:
            if not isinstance(entry, dict):
                kept.append(entry)
                continue
            key = _slug_label(entry.get("key") or entry.get("name"))
            if key == from_key:
                if existing_to is not None:
                    mutated = True
                    continue
                new_entry = dict(entry)
                new_entry["key"] = to_key
                kept.append(new_entry)
                mutated = True
            else:
                kept.append(entry)
        if mutated:
            scores[DISCOVERED_METRICS_KEY] = kept
            row.metric_scores = dict(scores)
            flag_modified(row, "metric_scores")

    raw_aliases = (
        evaluation.discovered_metric_aliases
        if isinstance(evaluation.discovered_metric_aliases, dict)
        else {}
    )
    aliases = dict(raw_aliases)
    canonical_to = _resolve_alias(aliases, to_key)
    aliases[from_key] = canonical_to
    for k, v in list(aliases.items()):
        if v == from_key:
            aliases[k] = canonical_to
    evaluation.discovered_metric_aliases = aliases

    db.commit()

    items_raw = _get_running_discovered_metrics(
        db,
        eval_id,
        organization_id=organization_id,
        alias_map=_flat_metric_aliases(evaluation),
    )
    return DiscoveredMetricsResponse(
        evaluation_id=evaluation.id,
        items=[DiscoveredMetricItem(**item) for item in items_raw],
    )


@router.post(
    "/{eval_id}/discovered-metrics/delete",
    response_model=DiscoveredMetricsResponse,
    operation_id="deleteCallImportEvaluationDiscoveredMetric",
)
async def delete_call_import_evaluation_discovered_metric(
    call_import_id: UUID,
    eval_id: UUID,
    body: DiscoveredMetricDeleteRequest,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> DiscoveredMetricsResponse:
    """Tombstone a single LLM-discovered top-level metric candidate."""

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

    target_key = _slug_label(body.key)
    if not target_key:
        raise HTTPException(
            status_code=400,
            detail="key must be a non-empty slug.",
        )

    rows = (
        db.query(CallImportEvaluationRow)
        .filter(CallImportEvaluationRow.evaluation_id == eval_id)
        .all()
    )

    for row in rows:
        scores = (
            row.metric_scores
            if isinstance(row.metric_scores, dict)
            else None
        )
        if not scores:
            continue
        discovered = scores.get(DISCOVERED_METRICS_KEY)
        if not isinstance(discovered, list):
            continue
        kept = [
            e
            for e in discovered
            if not (
                isinstance(e, dict)
                and _slug_label(e.get("key") or e.get("name"))
                == target_key
            )
        ]
        if len(kept) != len(discovered):
            if kept:
                scores[DISCOVERED_METRICS_KEY] = kept
            else:
                scores.pop(DISCOVERED_METRICS_KEY, None)
            row.metric_scores = dict(scores)
            flag_modified(row, "metric_scores")

    raw_aliases = (
        evaluation.discovered_metric_aliases
        if isinstance(evaluation.discovered_metric_aliases, dict)
        else {}
    )
    aliases = dict(raw_aliases)
    aliases[target_key] = ""  # tombstone
    for k, v in list(aliases.items()):
        if v == target_key:
            aliases[k] = ""
    evaluation.discovered_metric_aliases = aliases

    db.commit()

    items_raw = _get_running_discovered_metrics(
        db,
        eval_id,
        organization_id=organization_id,
        alias_map=_flat_metric_aliases(evaluation),
    )
    return DiscoveredMetricsResponse(
        evaluation_id=evaluation.id,
        items=[DiscoveredMetricItem(**item) for item in items_raw],
    )


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


# ---------------------------------------------------------------------------
# Retry endpoints
# ---------------------------------------------------------------------------
#
# The create endpoint enqueues every row of a fresh run; these endpoints
# let the user re-enqueue a *subset* of rows in an existing run — most
# commonly the ones that failed. We keep the worker contract identical
# (``evaluate_call_import_row_task(eval_row_id)``), so the retry path
# only has to reset row state and re-fan-out. When a row is missing its
# diarised transcript and the run was configured for diarised
# transcripts, we chain through ``transcribe_call_import_row_task`` the
# same way the create endpoint does — that's what makes "retry" feel
# like "just fix it" instead of "fail again immediately".


def _reset_eval_row_for_retry(
    eval_row: CallImportEvaluationRow,
    *,
    metric_ids: Optional[List[UUID]] = None,
) -> None:
    """Wipe per-row state so the worker can re-run it cleanly.

    Mirrors the initial state used by ``create_call_import_evaluation``
    when it first inserts a row, with the addition of revoking any
    lingering Celery task id.

    When ``metric_ids`` is provided, this is a **metric-subset retry**:
    only the scores for those metrics are removed from
    ``metric_scores`` (other metrics' previously-computed values are
    preserved so the worker's partial-merge write keeps them intact).
    Otherwise the entire ``metric_scores`` dict is reset, matching the
    legacy behaviour.
    """
    if eval_row.celery_task_id and eval_row.status in {"pending", "running"}:
        try:
            from app.workers.celery_app import celery_app

            celery_app.control.revoke(eval_row.celery_task_id, terminate=False)
        except Exception:  # noqa: BLE001 — revoke is best-effort
            pass
    eval_row.status = "pending"
    eval_row.error_message = None
    if metric_ids:
        # Strip ONLY the targeted metric keys. Both string and UUID
        # forms can appear in ``metric_scores`` depending on which
        # code path wrote the dict, so we normalise to lower-case
        # strings for the comparison.
        existing = (
            eval_row.metric_scores if isinstance(eval_row.metric_scores, dict) else {}
        )
        target_keys = {str(mid).lower() for mid in metric_ids}
        eval_row.metric_scores = {
            key: value
            for key, value in existing.items()
            if str(key).lower() not in target_keys
        }
    else:
        eval_row.metric_scores = {}
    eval_row.started_at = None
    eval_row.finished_at = None
    eval_row.celery_task_id = None


def _enqueue_eval_rows_with_optional_transcribe(
    db: Session,
    evaluation: CallImportEvaluation,
    eval_rows_with_source: List[
        Tuple[CallImportEvaluationRow, CallImportRow]
    ],
    *,
    transcribe_overwrite: bool = False,
    restricted_metric_ids: Optional[List[UUID]] = None,
) -> Tuple[int, int]:
    """Fan out evaluate (and optionally transcribe) tasks for a set of
    already-reset eval rows.

    Returns ``(evaluate_only_count, transcribe_then_evaluate_count)``.

    The transcribe-chain branch fires when the parent evaluation is
    configured for the diarised transcript source AND we have STT
    config saved on the run AND either (a) the row's diarised
    transcript is missing or (b) the caller passed
    ``transcribe_overwrite=True`` (used when the caller swapped the
    STT provider/model on retry and wants the new STT actually
    exercised). This matches the auto-transcribe behavior baked into
    the create endpoint so retry stays consistent with first-run.
    """
    from app.workers.tasks.evaluate_call_import_row import (
        evaluate_call_import_row_task,
    )
    from celery import group

    transcript_source = (evaluation.transcript_source or "").strip().lower()
    is_diarised_run = transcript_source == "diarised"
    # ``transcribe_mode`` was added in migration 041; legacy runs read as
    # NULL → default to the historical ``stt_llm`` behavior so retries
    # of pre-feature evaluations stay byte-identical.
    transcribe_mode = (
        getattr(evaluation, "transcribe_mode", None) or "stt_llm"
    ).strip().lower()
    has_stt_config = bool(evaluation.stt_provider and evaluation.stt_model)
    has_diariser_config = bool(
        getattr(evaluation, "diarisation_llm_provider", None)
        and getattr(evaluation, "diarisation_llm_model", None)
    )
    # In ``llm_only`` mode the run never had STT config (the create
    # endpoint rejects it), so ``has_stt_config`` would be False — but
    # we still want to chain through transcribe because the LLM is
    # what produces the diarised text. Gate on the diariser config
    # instead in that case.
    can_auto_transcribe = (
        has_stt_config if transcribe_mode == "stt_llm" else has_diariser_config
    )

    eval_only_row_ids: List[str] = []
    deferred: List[Tuple[CallImportEvaluationRow, CallImportRow]] = []
    for eval_row, source_row in eval_rows_with_source:
        has_audio = bool((source_row.recording_s3_key or "").strip())
        existing_dia = (source_row.diarised_transcript or "").strip()
        needs_diarisation = not existing_dia or transcribe_overwrite
        if (
            is_diarised_run
            and can_auto_transcribe
            and has_audio
            and needs_diarisation
        ):
            deferred.append((eval_row, source_row))
            continue
        eval_only_row_ids.append(str(eval_row.id))

    if deferred:
        from app.workers.tasks.transcribe_call_import_row import (
            transcribe_call_import_row_task,
        )

        # Mark the source rows as pending so the UI's diarisation badge
        # flips immediately, before Celery picks them up.
        for _, source_row in deferred:
            source_row.diarised_transcript_status = "pending"
            source_row.diarised_transcript_error = None
        db.commit()

        # ``restricted_metric_ids`` propagates through the transcribe
        # task as a kwarg so the evaluate task chained at the end of
        # transcribe (see ``transcribe_call_import_row_task``'s
        # ``run_eval_row_id`` branch) can apply the same metric
        # filter. Stringify so Celery's JSON serializer is happy.
        restricted_metric_ids_str: Optional[List[str]] = (
            [str(mid) for mid in restricted_metric_ids]
            if restricted_metric_ids
            else None
        )

        for eval_row, source_row in deferred:
            transcribe_call_import_row_task.apply_async(
                args=(
                    str(source_row.id),
                    # STT fields are ignored by the worker in llm_only
                    # mode; passing None keeps the wire format clean
                    # and avoids accidentally re-introducing stale
                    # config.
                    evaluation.stt_provider
                    if transcribe_mode == "stt_llm"
                    else None,
                    evaluation.stt_model
                    if transcribe_mode == "stt_llm"
                    else None,
                    str(evaluation.stt_credential_id)
                    if (
                        transcribe_mode == "stt_llm"
                        and evaluation.stt_credential_id
                    )
                    else None,
                    None,  # language hint not persisted on the run
                    transcribe_overwrite,
                    str(eval_row.id),
                    getattr(evaluation, "diarisation_llm_provider", None),
                    getattr(evaluation, "diarisation_llm_model", None),
                    str(evaluation.diarisation_llm_credential_id)
                    if getattr(
                        evaluation, "diarisation_llm_credential_id", None
                    )
                    else None,
                    getattr(evaluation, "diarisation_prompt", None),
                    transcribe_mode,
                ),
                kwargs={
                    "eval_restricted_metric_ids": restricted_metric_ids_str,
                }
                if restricted_metric_ids_str
                else None,
            )

    if eval_only_row_ids:
        if restricted_metric_ids:
            restricted_str = [str(mid) for mid in restricted_metric_ids]
            group(
                [
                    evaluate_call_import_row_task.s(
                        eval_row_id,
                        restricted_metric_ids=restricted_str,
                    )
                    for eval_row_id in eval_only_row_ids
                ]
            ).apply_async()
        else:
            group(
                [
                    evaluate_call_import_row_task.s(eval_row_id)
                    for eval_row_id in eval_only_row_ids
                ]
            ).apply_async()

    return len(eval_only_row_ids), len(deferred)


def _apply_retry_overrides(
    db: Session,
    evaluation: CallImportEvaluation,
    organization_id: UUID,
    payload: CallImportEvaluationRetryRequest,
) -> None:
    """Validate + persist the LLM/STT override fields on the run.

    Mirrors the validation in ``create_call_import_evaluation`` but
    only touches the fields the caller actually sent — leaving any
    field ``None`` preserves the run's existing value. Raises
    ``HTTPException(400)`` on bad input so the route handler can let
    FastAPI turn it into a clean 400 response.
    """
    # --- LLM provider + model (must be sent together) ---
    if payload.llm_provider is not None or payload.llm_model is not None:
        if not (payload.llm_provider and payload.llm_model):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Both llm_provider and llm_model are required when "
                    "overriding the run LLM on retry."
                ),
            )
        try:
            evaluation.llm_provider = ModelProvider(
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
        new_model = payload.llm_model.strip() or None
        if not new_model:
            raise HTTPException(
                status_code=400, detail="llm_model cannot be empty."
            )
        evaluation.llm_model = new_model

    # --- LLM credential pin ---
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
                    "The provided llm_credential_id does not exist in "
                    "this organization."
                ),
            )
        evaluation.llm_credential_id = payload.llm_credential_id

    # --- Per-metric LLM overrides ---
    # We accept the same dict shape as the create endpoint but
    # constrain keys to leaf metrics that are actually in this run.
    # Passing an empty dict explicitly clears existing overrides.
    if payload.metric_llm_overrides is not None:
        valid_leaf_ids = {
            str(mid) for mid in (evaluation.selected_metric_ids or [])
        }
        overrides_payload: Dict[str, Dict[str, Any]] = {}
        for metric_id, override in payload.metric_llm_overrides.items():
            if metric_id not in valid_leaf_ids:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "metric_llm_overrides references metric "
                        f"{metric_id} which is not a leaf metric in "
                        "this run."
                    ),
                )
            override_dict: Dict[str, Any] = {}
            if override.provider is not None:
                if not override.model:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"Override for metric {metric_id} has a "
                            "provider but no model."
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
                            f"Override for metric {metric_id} uses "
                            f"unknown provider '{override.provider}'."
                        ),
                    )
                override_dict["model"] = override.model.strip()
            elif override.model:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Override for metric {metric_id} has a model "
                        "but no provider."
                    ),
                )
            if override.credential_id is not None:
                override_dict["credential_id"] = str(override.credential_id)
            if override_dict:
                overrides_payload[metric_id] = override_dict
        evaluation.metric_llm_overrides = overrides_payload or None

    # --- STT provider + model (must be sent together) ---
    if payload.stt_provider is not None or payload.stt_model is not None:
        if not (payload.stt_provider and payload.stt_model):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Both stt_provider and stt_model are required "
                    "when overriding the run STT on retry."
                ),
            )
        try:
            evaluation.stt_provider = ModelProvider(
                payload.stt_provider.lower()
            ).value
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown STT provider '{payload.stt_provider}'.",
            )
        new_stt_model = payload.stt_model.strip() or None
        if not new_stt_model:
            raise HTTPException(
                status_code=400, detail="stt_model cannot be empty."
            )
        evaluation.stt_model = new_stt_model

    # --- STT credential pin ---
    if payload.stt_credential_id is not None:
        evaluation.stt_credential_id = payload.stt_credential_id

    # --- LLM diariser provider + model (must be sent together) ---
    if (
        payload.diarization_llm_provider is not None
        or payload.diarization_llm_model is not None
    ):
        if not (
            payload.diarization_llm_provider
            and payload.diarization_llm_model
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Both diarization_llm_provider and "
                    "diarization_llm_model are required when overriding "
                    "the run diariser on retry."
                ),
            )
        try:
            evaluation.diarisation_llm_provider = ModelProvider(
                payload.diarization_llm_provider.lower()
            ).value
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Unknown diarisation LLM provider "
                    f"'{payload.diarization_llm_provider}'."
                ),
            )
        new_diariser_model = (
            payload.diarization_llm_model.strip() or None
        )
        if not new_diariser_model:
            raise HTTPException(
                status_code=400,
                detail="diarization_llm_model cannot be empty.",
            )
        evaluation.diarisation_llm_model = new_diariser_model

    if payload.diarization_llm_credential_id is not None:
        evaluation.diarisation_llm_credential_id = (
            payload.diarization_llm_credential_id
        )

    # ``diarization_prompt`` semantics: None = leave untouched;
    # empty string = clear (fall back to the canonical default at
    # worker time); anything else = persist verbatim.
    if payload.diarization_prompt is not None:
        cleaned = payload.diarization_prompt.strip()
        evaluation.diarisation_prompt = cleaned or None


def _gather_retry_targets(
    db: Session,
    evaluation: CallImportEvaluation,
    requested_ids: Optional[List[UUID]],
    *,
    include_completed: bool = False,
) -> Tuple[
    List[Tuple[CallImportEvaluationRow, CallImportRow]],
    List[CallImportEvaluationRetrySkippedItem],
]:
    """Resolve which rows to retry + reasons for any we refuse.

    When ``requested_ids`` is None we retry every row whose status is
    ``failed`` (or every row when ``include_completed`` is also set —
    used by the metric-subset retry path which legitimately wants to
    recompute a metric on already-successful rows). When the caller
    passes ids explicitly we still filter out rows that are currently
    in flight; ``include_completed`` controls whether previously-
    successful rows are eligible.
    """
    eval_rows_query = db.query(CallImportEvaluationRow).filter(
        CallImportEvaluationRow.evaluation_id == evaluation.id
    )

    targets: List[Tuple[CallImportEvaluationRow, CallImportRow]] = []
    skipped: List[CallImportEvaluationRetrySkippedItem] = []

    if requested_ids is None:
        if include_completed:
            # "Retry everything" path used by the metric-subset re-run
            # UI. Still skip in-flight rows below so we don't trample
            # work the worker is actively doing.
            candidate_rows = eval_rows_query.filter(
                CallImportEvaluationRow.status.in_(["failed", "completed"])
            ).all()
        else:
            candidate_rows = eval_rows_query.filter(
                CallImportEvaluationRow.status == "failed"
            ).all()
    else:
        requested_set = set(requested_ids)
        candidate_rows = eval_rows_query.filter(
            CallImportEvaluationRow.id.in_(requested_set)
        ).all()
        found_ids = {row.id for row in candidate_rows}
        for missing in requested_set - found_ids:
            skipped.append(
                CallImportEvaluationRetrySkippedItem(
                    eval_row_id=missing,
                    reason="unknown",
                )
            )

    if not candidate_rows:
        return targets, skipped

    source_row_ids = [row.call_import_row_id for row in candidate_rows]
    source_rows = (
        db.query(CallImportRow)
        .filter(CallImportRow.id.in_(source_row_ids))
        .all()
    )
    source_by_id = {row.id: row for row in source_rows}

    for eval_row in candidate_rows:
        if eval_row.status in {"pending", "running"}:
            skipped.append(
                CallImportEvaluationRetrySkippedItem(
                    eval_row_id=eval_row.id,
                    reason="in_progress",
                )
            )
            continue
        if eval_row.status == "completed" and not include_completed:
            skipped.append(
                CallImportEvaluationRetrySkippedItem(
                    eval_row_id=eval_row.id,
                    reason="completed",
                )
            )
            continue
        source_row = source_by_id.get(eval_row.call_import_row_id)
        if source_row is None:
            skipped.append(
                CallImportEvaluationRetrySkippedItem(
                    eval_row_id=eval_row.id,
                    reason="source_row_missing",
                )
            )
            continue
        targets.append((eval_row, source_row))

    return targets, skipped


@router.post(
    "/{eval_id}/retry",
    response_model=CallImportEvaluationRetryResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="retryCallImportEvaluation",
)
async def retry_call_import_evaluation(
    call_import_id: UUID,
    eval_id: UUID,
    payload: Optional[CallImportEvaluationRetryRequest] = Body(default=None),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportEvaluationRetryResponse:
    """Re-enqueue failed rows in an evaluation run.

    Default behavior (no body) is "retry every row that failed". Pass
    ``eval_row_ids`` to scope the retry to a specific subset (e.g. the
    single row a user clicked in the UI). Rows that are still
    in-flight or already completed are returned in ``skipped`` rather
    than re-enqueued, so this endpoint is always safe to call.

    When ``metric_ids`` is set in the payload, this is a **metric-
    subset retry**: only the listed metrics are recomputed (and merged
    into the row's existing ``metric_scores`` — other metrics' values
    are preserved). The route auto-flips ``include_completed=True`` in
    that case so previously-successful rows are eligible for re-
    scoring; without it the call would no-op because every row would
    be skipped as ``completed``.

    The worker contract is the same as the create endpoint:
    ``evaluate_call_import_row_task(eval_row_id, [restricted_metric_ids])``.
    When the run is configured for diarised transcripts and the row's
    diarised transcript is missing, we chain through
    ``transcribe_call_import_row_task`` first — matching the
    auto-transcribe behavior of POST ``/evaluations``.
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

    requested_ids = payload.eval_row_ids if payload else None
    # Metric-subset retry: validate that every metric is something this
    # run actually scored. Empty list is rejected too — callers that
    # want a full re-run should omit the field entirely.
    #
    # ``selected_metric_ids`` holds the LEAVES only (children for
    # hierarchical / category metrics, standalone metrics otherwise) —
    # see ``leaf_metric_ids`` in :func:`create_call_import_evaluation`.
    # Parent IDs for hierarchical metrics live separately in
    # ``selected_metric_groups`` (``{parent_id: [child_ids]}``) so the
    # UI can reconstruct the tree without round-tripping through the
    # metric table.
    #
    # The Re-run-metrics modal surfaces PARENTS for hierarchical
    # metrics (it suppresses individual children via
    # ``childrenInGroups`` in ``CallImportEvaluationDetail.tsx``), so a
    # naive ``metric_ids ⊆ selected_metric_ids`` check rejects every
    # parent-ID request with a misleading "unknown ids" 400. We accept
    # both shapes here and then EXPAND any parent IDs into
    # ``{parent_id, *child_ids}`` so the downstream helpers see the
    # full set of keys that need clearing + the full set of leaves
    # that need re-scoring.
    metric_ids: Optional[List[UUID]] = (
        payload.metric_ids if payload else None
    )
    if metric_ids is not None:
        if not metric_ids:
            raise HTTPException(
                status_code=400,
                detail=(
                    "metric_ids must be a non-empty list. Omit the "
                    "field to re-run all metrics."
                ),
            )

        leaf_set: Set[str] = {
            str(item).lower()
            for item in (evaluation.selected_metric_ids or [])
        }
        # ``selected_metric_groups`` is a dict ``{parent_id_str:
        # [child_id_str, ...]}`` (see line ~487 in
        # ``create_call_import_evaluation``). We tolerate stale data
        # (string / UUID / non-dict) without crashing the retry path —
        # if it's malformed we just treat it as "no parents" and fall
        # back to the leaf-only check.
        groups_raw = (
            evaluation.selected_metric_groups
            if isinstance(evaluation.selected_metric_groups, dict)
            else {}
        )
        parent_to_children_str: Dict[str, List[str]] = {}
        for parent_key, children_raw in groups_raw.items():
            if not isinstance(children_raw, (list, tuple)):
                continue
            children_norm = [
                str(c).lower() for c in children_raw if c is not None
            ]
            parent_to_children_str[str(parent_key).lower()] = children_norm
        parent_set = set(parent_to_children_str.keys())

        unknown = [
            mid for mid in metric_ids
            if str(mid).lower() not in leaf_set
            and str(mid).lower() not in parent_set
        ]
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=(
                    "metric_ids must be a subset of this evaluation's "
                    f"selected metrics; unknown ids: {[str(u) for u in unknown]}."
                ),
            )

        # Expand parent IDs into ``{parent, *children}`` so:
        #   * ``_reset_eval_row_for_retry`` strips BOTH the parent
        #     entry (with ``chosen_child_id`` / rationale) AND every
        #     per-child boolean entry that the LLM evaluator wrote
        #     under each child's ID (see
        #     ``app/workers/tasks/helpers/llm_evaluation.py`` lines
        #     1584 and 1649).
        #   * ``_enqueue_eval_rows_with_optional_transcribe`` →
        #     ``evaluate_call_import_row_task`` filters the work-list
        #     off ``selected_metric_ids`` (leaves), so we MUST hand it
        #     the child IDs for the parent to actually get re-scored.
        # Leaves pass through unchanged.
        expanded: List[UUID] = []
        seen: Set[str] = set()
        for mid in metric_ids:
            mid_norm = str(mid).lower()
            children_str = parent_to_children_str.get(mid_norm)
            if children_str is not None:
                # Parent: include the parent ID itself (so the parent
                # entry in ``metric_scores`` is also cleared) and all
                # of its children.
                candidates = [mid_norm, *children_str]
            else:
                candidates = [mid_norm]
            for candidate in candidates:
                if candidate in seen:
                    continue
                try:
                    expanded.append(UUID(candidate))
                except (TypeError, ValueError):
                    # Defensive: skip junk values rather than 500.
                    continue
                seen.add(candidate)
        metric_ids = expanded

    # ``include_completed`` is auto-enabled when the caller asked for a
    # metric subset (otherwise the metric-subset retry would always
    # no-op on a green run, which is the whole reason this feature
    # exists). The explicit payload flag wins for full-row retries.
    include_completed = bool(
        (payload.include_completed if payload else False)
        or (metric_ids is not None)
    )

    targets, skipped = _gather_retry_targets(
        db,
        evaluation,
        requested_ids,
        include_completed=include_completed,
    )

    if not targets:
        # Nothing actually changed — return early without touching the
        # parent so we don't flip a completed run into "running" by
        # mistake.
        return CallImportEvaluationRetryResponse(
            requeued=0,
            transcribe_requeued=0,
            skipped=skipped,
        )

    # Apply LLM / STT overrides BEFORE resetting rows so the persisted
    # run config is correct by the time the worker reads it. Validation
    # happens here too — bad overrides 400 without touching any row
    # state.
    if payload is not None:
        _apply_retry_overrides(db, evaluation, organization_id, payload)
    transcribe_overwrite = bool(
        payload.transcribe_overwrite if payload else False
    )

    for eval_row, _ in targets:
        _reset_eval_row_for_retry(eval_row, metric_ids=metric_ids)

    # Flip the parent back to ``running`` and clear any old enqueue
    # error so the UI's polling resumes. Counters get recomputed by
    # the worker's ``_rollup_parent`` as rows finish, but we also call
    # the route-side rollup helper here so the counts are immediately
    # consistent with the new pending rows.
    evaluation.error_message = None
    evaluation.finished_at = None
    db.flush()
    _rollup_evaluation_status(evaluation, db)
    db.commit()

    try:
        evaluate_only, transcribe_chain = (
            _enqueue_eval_rows_with_optional_transcribe(
                db,
                evaluation,
                targets,
                transcribe_overwrite=transcribe_overwrite,
                restricted_metric_ids=metric_ids,
            )
        )
    except Exception as exc:  # noqa: BLE001 — surface but don't 500
        logger.exception(
            "Failed to re-enqueue evaluation {} for call import {}",
            eval_id,
            call_import_id,
        )
        # Roll the targeted rows back to ``failed`` with a clear
        # message — leaving them ``pending`` would make the UI think
        # work is still happening.
        for eval_row, _ in targets:
            eval_row.status = "failed"
            eval_row.error_message = f"Failed to re-enqueue retry: {exc}"
        _rollup_evaluation_status(evaluation, db)
        db.commit()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to re-enqueue retry: {exc}",
        )

    return CallImportEvaluationRetryResponse(
        requeued=evaluate_only + transcribe_chain,
        transcribe_requeued=transcribe_chain,
        skipped=skipped,
    )


@router.post(
    "/{eval_id}/rows/{eval_row_id}/retry",
    response_model=CallImportEvaluationRowResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="retryCallImportEvaluationRow",
)
async def retry_call_import_evaluation_row(
    call_import_id: UUID,
    eval_id: UUID,
    eval_row_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportEvaluationRowResponse:
    """Re-enqueue a single failed evaluation row.

    Convenience wrapper around ``retry_call_import_evaluation`` for the
    "Retry this row" affordance in the row table. Returns the
    refreshed row so the UI can update its badge immediately, without
    waiting for the next polling tick.
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

    if eval_row.status in {"pending", "running"}:
        raise HTTPException(
            status_code=409,
            detail=(
                "This row is still in progress — wait for it to finish "
                "before retrying."
            ),
        )

    targets, _ = _gather_retry_targets(db, evaluation, [eval_row.id])
    if not targets:
        # Status was ``completed`` (or source row vanished) — surface a
        # 409 instead of silently no-op'ing so the UI can show why.
        raise HTTPException(
            status_code=409,
            detail=(
                "This row cannot be retried in its current state "
                f"(status={eval_row.status})."
            ),
        )

    for er, _ in targets:
        _reset_eval_row_for_retry(er)

    evaluation.error_message = None
    evaluation.finished_at = None
    db.flush()
    _rollup_evaluation_status(evaluation, db)
    db.commit()

    try:
        _enqueue_eval_rows_with_optional_transcribe(db, evaluation, targets)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Failed to re-enqueue retry for evaluation row {}", eval_row_id
        )
        eval_row.status = "failed"
        eval_row.error_message = f"Failed to re-enqueue retry: {exc}"
        _rollup_evaluation_status(evaluation, db)
        db.commit()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to re-enqueue retry: {exc}",
        )

    db.refresh(eval_row)
    source_row = targets[0][1]
    return CallImportEvaluationRowResponse(
        id=eval_row.id,
        evaluation_id=eval_row.evaluation_id,
        call_import_row_id=eval_row.call_import_row_id,
        row_index=source_row.row_index,
        conversation_id=source_row.conversation_id,
        transcript=source_row.transcript,
        raw_columns=source_row.raw_columns,
        recording_url=source_row.recording_url,
        recording_s3_key=source_row.recording_s3_key,
        status=eval_row.status,
        metric_scores=eval_row.metric_scores or {},
        error_message=eval_row.error_message,
        started_at=eval_row.started_at,
        finished_at=eval_row.finished_at,
        created_at=eval_row.created_at,
        updated_at=eval_row.updated_at,
    )
