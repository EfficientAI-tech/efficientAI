"""Evaluation export jobs and PDF report route wrappers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import Body, Depends, HTTPException, status
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.auth import Principal, get_principal
from app.core.auth.capabilities import REPORTS_GENERATE
from app.database import get_db
from app.dependencies import get_api_key, get_organization_id
from app.models.database import CallImportEvaluation, CallImportEvaluationPdfReport
from app.models.schemas import (
    CallImportEvaluationExportJobResponse,
    CallImportEvaluationExportRequest,
)
from app.services.reporting.call_import_evaluation_pdf_api import (
    CallImportEvaluationBaselineCandidatesResponse,
    CallImportEvaluationPdfReportListResponse,
    CallImportEvaluationPdfReportRequest,
    CallImportEvaluationPdfReportResponse,
    baseline_candidates_response,
    generate_call_import_evaluation_pdf_report,
    pdf_report_download_response,
    pdf_report_list_item_from_row,
    pdf_report_response_from_row,
)

from app.api.v1.routes.call_import_evaluations._router import router
from app.api.v1.routes.call_import_evaluations._shared import (
    _require_import,
    require_call_import_capability,
)

@router.post(
    "/{eval_id}/export",
    response_model=CallImportEvaluationExportJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="startCallImportEvaluationExport",
)
async def start_call_import_evaluation_export(
    call_import_id: UUID,
    eval_id: UUID,
    payload: Optional[CallImportEvaluationExportRequest] = Body(None),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportEvaluationExportJobResponse:
    """Queue a gzip CSV (or scores-only xlsx) export and return the job.

    The file is built off this request. Poll the job, then download each
    part from blob storage.
    """
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

    from sqlalchemy.exc import IntegrityError

    from app.models.database import CallImportEvaluationExport
    from app.services.call_imports.evaluation_export import (
        XLSX_SHEET_ROW_CAP,
        execute_evaluation_export,
        export_job_is_stale,
    )
    from app.services.storage.blob_storage_service import blob_storage_service

    body = payload or CallImportEvaluationExportRequest()
    if body.format == "xlsx":
        from app.db_sharding.eval_rows import count_evaluation_rows_for_run

        row_count = count_evaluation_rows_for_run(db, eval_id)
        if row_count > XLSX_SHEET_ROW_CAP:
            raise HTTPException(
                status_code=400,
                detail=(
                    "This run has more rows than Excel allows on one sheet. "
                    "Download the CSV instead."
                ),
            )

    active = _active_export_job(db, eval_id)
    if active is not None and not _export_request_matches(active, body):
        was_stale = export_job_is_stale(active)
        if was_stale and _fail_stale_export_job(db, active):
            active = None
        elif was_stale:
            active = _active_export_job(db, eval_id)
        if active is not None and not _export_request_matches(active, body):
            raise HTTPException(
                status_code=409,
                detail=(
                    "An export is already running for this evaluation. "
                    "Wait for it to finish before starting a different download."
                ),
            )
    if active is not None:
        if blob_storage_service.is_enabled() and (
            active.status == "pending" or export_job_is_stale(active)
        ):
            try:
                _enqueue_evaluation_export(str(active.id))
            except Exception as exc:
                if active.status == "pending":
                    active.status = "failed"
                    active.error_message = f"Could not queue the export: {exc}"
                    active.finished_at = datetime.now(timezone.utc)
                    db.commit()
                    db.refresh(active)
        return _export_job_response(active)

    job = CallImportEvaluationExport(
        evaluation_id=evaluation.id,
        call_import_id=call_import.id,
        organization_id=organization_id,
        workspace_id=call_import.workspace_id,
        format=body.format,
        include_transcripts=body.include_transcripts,
        status="pending",
        parts=[],
    )
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        active = _active_export_job(db, eval_id)
        if active is not None and _export_request_matches(active, body):
            return _export_job_response(active)
        if active is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "An export is already running for this evaluation. "
                    "Wait for it to finish before starting a different download."
                ),
            )
        raise
    db.refresh(job)

    if not blob_storage_service.is_enabled():
        execute_evaluation_export(db, job.id)
        db.refresh(job)
        return _export_job_response(job)

    try:
        _enqueue_evaluation_export(str(job.id))
    except Exception as exc:
        job.status = "failed"
        job.error_message = f"Could not queue the export: {exc}"
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(job)
    return _export_job_response(job)


@router.get(
    "/{eval_id}/export-jobs/{job_id}",
    response_model=CallImportEvaluationExportJobResponse,
    operation_id="getCallImportEvaluationExport",
)
async def get_call_import_evaluation_export(
    call_import_id: UUID,
    eval_id: UUID,
    job_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportEvaluationExportJobResponse:
    del api_key
    _require_import(db, call_import_id, organization_id)
    from app.models.database import CallImportEvaluationExport

    job = (
        db.query(CallImportEvaluationExport)
        .filter(
            CallImportEvaluationExport.id == job_id,
            CallImportEvaluationExport.evaluation_id == eval_id,
            CallImportEvaluationExport.call_import_id == call_import_id,
            CallImportEvaluationExport.organization_id == organization_id,
        )
        .first()
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Export job not found")
    return _export_job_response(job, with_download_urls=True)


def _fail_stale_export_job(db: Session, job) -> bool:
    """Fail a stale running export only while that same claim still holds it.

    The heartbeat and claim are the values already loaded on ``job``. A
    worker that claimed the export after this read changes both, the
    update matches nothing, and the caller re-reads the live job.
    """
    from sqlalchemy import update

    from app.models.database import CallImportEvaluationExport

    observed_heartbeat = job.heartbeat_at
    observed_claim = job.claim_token
    heartbeat_still = (
        CallImportEvaluationExport.heartbeat_at.is_(None)
        if observed_heartbeat is None
        else CallImportEvaluationExport.heartbeat_at == observed_heartbeat
    )
    claim_still = (
        CallImportEvaluationExport.claim_token.is_(None)
        if observed_claim is None
        else CallImportEvaluationExport.claim_token == observed_claim
    )
    result = db.execute(
        update(CallImportEvaluationExport)
        .where(
            CallImportEvaluationExport.id == job.id,
            CallImportEvaluationExport.status == "running",
            heartbeat_still,
            claim_still,
        )
        .values(
            status="failed",
            error_message="Stopped because a different export was requested.",
            finished_at=datetime.now(timezone.utc),
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return bool(result.rowcount)


def _export_request_matches(job, body) -> bool:
    return (job.format or "csv") == body.format and bool(job.include_transcripts) == bool(
        body.include_transcripts
    )


def _active_export_job(db: Session, evaluation_id: UUID):
    from app.models.database import CallImportEvaluationExport

    return (
        db.query(CallImportEvaluationExport)
        .filter(
            CallImportEvaluationExport.evaluation_id == evaluation_id,
            CallImportEvaluationExport.status.in_(("pending", "running")),
        )
        .first()
    )


def _enqueue_evaluation_export(job_id: str) -> None:
    from app.workers.tasks.call_import_bulk_ops import (
        export_call_import_evaluation_task,
    )

    export_call_import_evaluation_task.delay(job_id)


def _export_job_response(job, *, with_download_urls: bool = False):
    from app.models.schemas import (
        CallImportEvaluationExportJobResponse,
        CallImportEvaluationExportPart,
    )
    from app.services.call_imports.evaluation_export import EXPORT_URL_TTL_SECONDS
    from app.services.storage.blob_storage_service import blob_storage_service

    parts = []
    raw_parts = job.parts if isinstance(job.parts, list) else []
    for item in raw_parts:
        if not isinstance(item, dict):
            continue
        download_url = None
        key = item.get("s3_key")
        filename = item.get("filename") or "export.csv.gz"
        if (
            with_download_urls
            and job.status == "completed"
            and key
            and blob_storage_service.is_enabled()
        ):
            download_url = blob_storage_service.generate_presigned_url_by_key(
                key,
                expiration=EXPORT_URL_TTL_SECONDS,
                response_content_disposition=f'attachment; filename="{filename}"',
            )
        parts.append(
            CallImportEvaluationExportPart(
                part=int(item.get("part") or 0),
                filename=filename,
                row_count=int(item.get("row_count") or 0),
                byte_size=int(item.get("byte_size") or 0),
                download_url=download_url,
            )
        )
    return CallImportEvaluationExportJobResponse(
        id=job.id,
        evaluation_id=job.evaluation_id,
        status=job.status,
        format=job.format,
        include_transcripts=bool(job.include_transcripts),
        error_message=job.error_message,
        parts=parts,
    )

@router.get(
    "/{eval_id}/baseline-candidates",
    response_model=CallImportEvaluationBaselineCandidatesResponse,
    operation_id="listCallImportEvaluationBaselineCandidates",
)
async def list_call_import_evaluation_baseline_candidates(
    call_import_id: UUID,
    eval_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportEvaluationBaselineCandidatesResponse:
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
    return baseline_candidates_response(
        db,
        call_import=call_import,
        evaluation=evaluation,
        organization_id=organization_id,
    )


@router.post(
    "/{eval_id}/pdf-report",
    operation_id="generateCallImportEvaluationPdfReport",
    dependencies=[Depends(require_call_import_capability(REPORTS_GENERATE))],
)
async def generate_call_import_evaluation_pdf_report_route(
    call_import_id: UUID,
    eval_id: UUID,
    payload: CallImportEvaluationPdfReportRequest,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
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
    return await generate_call_import_evaluation_pdf_report(
        db,
        call_import=call_import,
        evaluation=evaluation,
        organization_id=organization_id,
        eval_id=eval_id,
        call_import_id=call_import_id,
        payload=payload,
        principal=principal,
    )


@router.get(
    "/{eval_id}/pdf-reports",
    response_model=CallImportEvaluationPdfReportListResponse,
    operation_id="listCallImportEvaluationPdfReports",
)
async def list_call_import_evaluation_pdf_reports(
    call_import_id: UUID,
    eval_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportEvaluationPdfReportListResponse:
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

    rows = (
        db.query(CallImportEvaluationPdfReport)
        .filter(
            CallImportEvaluationPdfReport.evaluation_id == eval_id,
            CallImportEvaluationPdfReport.organization_id == organization_id,
        )
        .order_by(desc(CallImportEvaluationPdfReport.created_at))
        .all()
    )
    return CallImportEvaluationPdfReportListResponse(
        items=[pdf_report_list_item_from_row(row) for row in rows],
    )


@router.get(
    "/{eval_id}/pdf-reports/{report_id}",
    response_model=CallImportEvaluationPdfReportResponse,
    operation_id="getCallImportEvaluationPdfReport",
)
async def get_call_import_evaluation_pdf_report(
    call_import_id: UUID,
    eval_id: UUID,
    report_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportEvaluationPdfReportResponse:
    del api_key
    _require_import(db, call_import_id, organization_id)
    row = (
        db.query(CallImportEvaluationPdfReport)
        .filter(
            CallImportEvaluationPdfReport.id == report_id,
            CallImportEvaluationPdfReport.evaluation_id == eval_id,
            CallImportEvaluationPdfReport.call_import_id == call_import_id,
            CallImportEvaluationPdfReport.organization_id == organization_id,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="PDF report not found")
    if not row.s3_key:
        raise HTTPException(
            status_code=404,
            detail="PDF report file is not available in object storage",
        )
    return pdf_report_response_from_row(row)


@router.get(
    "/{eval_id}/pdf-reports/{report_id}/download",
    operation_id="downloadCallImportEvaluationPdfReport",
)
async def download_call_import_evaluation_pdf_report(
    call_import_id: UUID,
    eval_id: UUID,
    report_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    del api_key
    _require_import(db, call_import_id, organization_id)
    return pdf_report_download_response(
        db,
        call_import_id=call_import_id,
        eval_id=eval_id,
        report_id=report_id,
        organization_id=organization_id,
    )

