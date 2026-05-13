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


def _serialize_eval(db: Session, row: CallImportEvaluation) -> CallImportEvaluationResponse:
    selected_ids = _serialize_selected_metric_ids(row.selected_metric_ids)
    metrics = _metrics_for_ids(db, row.organization_id, selected_ids)
    return CallImportEvaluationResponse(
        id=row.id,
        call_import_id=row.call_import_id,
        organization_id=row.organization_id,
        name=row.name,
        selected_metric_ids=selected_ids,
        metrics=[
            CallImportMetricSummary(
                id=metric.id,
                name=metric.name,
                metric_type=metric.metric_type,
                description=metric.description,
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
    disabled = [metric for metric in org_metrics if not metric.enabled]
    if disabled:
        names = ", ".join(metric.name for metric in disabled)
        raise HTTPException(
            status_code=400,
            detail=(
                f"These metrics are disabled and cannot be evaluated: {names}. "
                "Enable them on the Metrics page (or pick different ones) and "
                "try again."
            ),
        )
    metric_rows = org_metrics
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

    # Per-metric overrides: allow keys only for metrics actually selected,
    # and validate provider strings the same way as the run-level default.
    metric_overrides_payload: Optional[Dict[str, Dict[str, Any]]] = None
    if payload.metric_llm_overrides:
        metric_overrides_payload = {}
        for metric_id, override in payload.metric_llm_overrides.items():
            if metric_id not in valid_metric_id_strs:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "metric_llm_overrides references metric "
                        f"{metric_id} which is not in metric_ids."
                    ),
                )
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
                metric_overrides_payload[metric_id] = override_dict

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
        selected_metric_ids=[str(metric_id) for metric_id in metric_ids],
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
    metrics = _metrics_for_ids(db, organization_id, selected_metric_ids)
    metric_names = {str(metric.id): metric.name for metric in metrics}

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

    # For each selected metric we emit one column for the value, and a
    # second "<Name> - LLM Rationale" column when the metric is configured
    # with ``capture_rationale=True``. This matches the reference CSV
    # layout (e.g. "Language adherence - LLM Label" + "Language adherence -
    # LLM Rationale").
    metric_headers: List[str] = []
    rationale_headers: Dict[str, str] = {}  # metric_id_str -> rationale column name
    for metric in metrics:
        header = metric_names[str(metric.id)]
        metric_headers.append(header)
        if bool(getattr(metric, "capture_rationale", False)):
            rationale_header = f"{header} - LLM Rationale"
            metric_headers.append(rationale_header)
            rationale_headers[str(metric.id)] = rationale_header
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
