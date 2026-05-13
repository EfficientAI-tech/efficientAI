"""Evaluation routes scoped to a Call Import batch."""

from __future__ import annotations

import csv
import io
from typing import Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_api_key, get_organization_id
from app.models.database import (
    CallImport,
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
    Metric,
)
from app.models.enums import CallImportRowStatus
from app.models.schemas import (
    CallImportEvaluationBulkDelete,
    CallImportEvaluationCreate,
    CallImportEvaluationListResponse,
    CallImportEvaluationResponse,
    CallImportEvaluationRowListResponse,
    CallImportEvaluationRowResponse,
    CallImportEvaluationUpdate,
    CallImportMetricSummary,
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
    )
    db.add(evaluation)
    db.flush()

    eval_rows: List[CallImportEvaluationRow] = []
    for source_row in completed_rows:
        eval_row = CallImportEvaluationRow(
            evaluation_id=evaluation.id,
            call_import_row_id=source_row.id,
            status="pending",
            metric_scores={},
        )
        db.add(eval_row)
        eval_rows.append(eval_row)

    db.commit()
    db.refresh(evaluation)

    if not eval_rows:
        evaluation.status = "completed"
        db.commit()
        db.refresh(evaluation)
        return _serialize_eval(db, evaluation)

    # Lazy imports keep test setup simple — tests stub the worker module so
    # importing the route never reaches into Celery's broker config.
    from celery import group
    from app.workers.tasks.evaluate_call_import_row import (
        evaluate_call_import_row_task,
    )

    try:
        sigs = [
            evaluate_call_import_row_task.s(str(eval_row.id)) for eval_row in eval_rows
        ]
        job = group(sigs).apply_async()
        evaluation.celery_group_id = getattr(job, "id", None)
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
        .order_by(CallImportRow.row_index.asc())
    )
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

    metric_headers = [metric_names[str(metric.id)] for metric in metrics]
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
        writer.writerow(row_out)

    # Excel on Windows defaults to the system ANSI codepage (Windows-1252)
    # when a CSV has no encoding marker, which turns UTF-8 Hindi/Devanagari
    # / any non-ASCII text into mojibake (e.g. ``ठीक`` → ``à¤ à¥€à¤•``).
    # A UTF-8 BOM tells Excel to switch to UTF-8 decoding and is silently
    # skipped by every other UTF-8-aware reader (pandas, LibreOffice,
    # Google Sheets, etc.), so the data round-trips correctly everywhere.
    csv_text = output.getvalue()
    csv_bytes = ("\ufeff" + csv_text).encode("utf-8")
    filename = f"call-import-{call_import_id}-evaluation-{eval_id}.csv"
    return StreamingResponse(
        iter([csv_bytes]),
        media_type="text/csv; charset=utf-8",
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
