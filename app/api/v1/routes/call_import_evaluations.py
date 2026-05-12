"""Evaluation routes scoped to a Call Import batch."""

from __future__ import annotations

import csv
import io
from typing import Dict, List
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
    CallImportEvaluationCreate,
    CallImportEvaluationListResponse,
    CallImportEvaluationResponse,
    CallImportEvaluationRowListResponse,
    CallImportEvaluationRowResponse,
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

    output.seek(0)
    filename = f"call-import-{call_import_id}-evaluation-{eval_id}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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

    if row.celery_group_id:
        try:
            from app.workers.celery_app import celery_app

            pending_task_ids = [
                eval_row.celery_task_id
                for eval_row in row.row_results
                if eval_row.celery_task_id and eval_row.status in {"pending", "running"}
            ]
            if pending_task_ids:
                celery_app.control.revoke(pending_task_ids, terminate=False)
        except Exception:
            # Best effort - DB delete is source of truth.
            pass

    db.delete(row)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
