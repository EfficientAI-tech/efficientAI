"""CSV-driven call import routes.

Users upload a CSV with columns CallID, Transcript (and optionally
Recording URL). The backend persists a CallImport batch + one
CallImportRow per line, then fans the rows out to the Celery `imports`
queue where each row is fetched from the configured voice provider
(currently Exotel) and stored in S3. When a row has no Recording URL,
the worker resolves it from the provider's call detail endpoint using
the CallID.
"""

from __future__ import annotations

import csv
import io
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from loguru import logger
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_api_key, get_organization_id
from app.models.database import (
    CallImport,
    CallImportRow,
    TelephonyIntegration,
)
from app.models.enums import (
    CallImportRowStatus,
    CallImportStatus,
    TelephonyProvider,
)
from app.models.schemas import (
    CallImportDetailResponse,
    CallImportListResponse,
    CallImportResponse,
    CallImportRowResponse,
    CallImportUploadResponse,
)


router = APIRouter(prefix="/call-imports", tags=["Call Imports"])


REQUIRED_HEADERS = {"callid", "transcript"}
OPTIONAL_HEADERS = {"recording url"}
MAX_CSV_BYTES = 10 * 1024 * 1024  # 10 MB CSV cap


def _normalize_header(name: str) -> str:
    return (name or "").strip().lower()


def _header_lookup(fieldnames: List[str]) -> dict[str, str]:
    """Map normalized header -> original header so DictReader access works regardless of case."""
    return {_normalize_header(h): h for h in fieldnames or []}


def _parse_csv(file_bytes: bytes) -> List[dict]:
    """Parse the CSV bytes into a list of {callid, recording_url, transcript} dicts.

    Raises HTTPException(400) on empty input, missing headers, or rows missing
    required values.
    """
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded CSV is empty.",
        )

    try:
        text_stream = io.StringIO(file_bytes.decode("utf-8-sig"))
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV must be UTF-8 encoded.",
        )

    reader = csv.DictReader(text_stream)
    if not reader.fieldnames:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV is missing a header row.",
        )

    headers = _header_lookup(reader.fieldnames)
    missing = REQUIRED_HEADERS - set(headers.keys())
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "CSV is missing required headers: "
                f"{sorted(missing)}. Required headers (case-insensitive): "
                "CallID, Transcript. Optional: Recording URL "
                "(resolved from the provider when omitted)."
            ),
        )

    callid_h = headers["callid"]
    url_h = headers.get("recording url")
    transcript_h = headers["transcript"]

    parsed: List[dict] = []
    for idx, row in enumerate(reader):
        call_id = (row.get(callid_h) or "").strip()
        url = (row.get(url_h) or "").strip() if url_h else ""
        transcript = (row.get(transcript_h) or "").strip()
        if not call_id and not url and not transcript:
            continue
        if not call_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Row {idx + 1} is missing CallID.",
            )
        parsed.append(
            {
                "external_call_id": call_id,
                "recording_url": url or None,
                "transcript": transcript or None,
            }
        )

    if not parsed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV did not contain any data rows.",
        )

    return parsed


@router.post(
    "/upload",
    response_model=CallImportUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="uploadCallImportCsv",
)
async def upload_call_import_csv(
    file: UploadFile = File(...),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportUploadResponse:
    """Accept a CSV (CallID, Recording URL, Transcript) and queue per-row import jobs."""

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be a .csv",
        )

    file_bytes = await file.read()
    if len(file_bytes) > MAX_CSV_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"CSV exceeds {MAX_CSV_BYTES} bytes",
        )

    rows = _parse_csv(file_bytes)

    integration = (
        db.query(TelephonyIntegration)
        .filter(
            TelephonyIntegration.organization_id == organization_id,
            TelephonyIntegration.provider == TelephonyProvider.EXOTEL.value,
            TelephonyIntegration.is_active.is_(True),
        )
        .first()
    )
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No active Exotel telephony integration is configured for this "
                "organization. Add one via /api/v1/telephony before importing."
            ),
        )

    call_import = CallImport(
        organization_id=organization_id,
        provider=TelephonyProvider.EXOTEL.value,
        original_filename=file.filename,
        total_rows=len(rows),
        completed_rows=0,
        failed_rows=0,
        status=CallImportStatus.PENDING,
    )
    db.add(call_import)
    db.flush()  # populate call_import.id

    row_models: List[CallImportRow] = []
    for idx, row in enumerate(rows):
        row_model = CallImportRow(
            call_import_id=call_import.id,
            organization_id=organization_id,
            row_index=idx,
            external_call_id=row["external_call_id"],
            recording_url=row["recording_url"],
            transcript=row["transcript"],
            status=CallImportRowStatus.PENDING,
        )
        db.add(row_model)
        row_models.append(row_model)

    call_import.status = CallImportStatus.PROCESSING
    db.commit()
    db.refresh(call_import)

    from app.workers.tasks.process_call_import_row import process_call_import_row_task

    for row_model in row_models:
        try:
            process_call_import_row_task.delay(str(row_model.id))
        except Exception as exc:
            logger.exception(
                "Failed to enqueue call import row {} for import {}",
                row_model.id,
                call_import.id,
            )
            row_model.status = CallImportRowStatus.FAILED
            row_model.error_message = f"Failed to enqueue: {exc}"
    db.commit()

    return CallImportUploadResponse(
        id=call_import.id,
        total_rows=call_import.total_rows,
        status=call_import.status,
        message=(
            f"Accepted {call_import.total_rows} rows for import. "
            "Recordings will be fetched asynchronously."
        ),
    )


@router.get(
    "",
    response_model=CallImportListResponse,
    operation_id="listCallImports",
)
async def list_call_imports(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[CallImportStatus] = Query(None, alias="status"),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportListResponse:
    """List call-import batches for the organization, newest first."""

    query = db.query(CallImport).filter(CallImport.organization_id == organization_id)
    if status_filter is not None:
        query = query.filter(CallImport.status == status_filter)

    total = query.count()
    items = (
        query.order_by(desc(CallImport.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return CallImportListResponse(
        items=[CallImportResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{call_import_id}",
    response_model=CallImportDetailResponse,
    operation_id="getCallImportDetail",
)
async def get_call_import_detail(
    call_import_id: UUID,
    row_limit: int = Query(500, ge=1, le=5000),
    row_offset: int = Query(0, ge=0),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportDetailResponse:
    """Fetch a single import batch with a slice of its rows."""

    call_import = (
        db.query(CallImport)
        .filter(
            CallImport.id == call_import_id,
            CallImport.organization_id == organization_id,
        )
        .first()
    )
    if not call_import:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call import not found",
        )

    rows = (
        db.query(CallImportRow)
        .filter(CallImportRow.call_import_id == call_import.id)
        .order_by(CallImportRow.row_index)
        .offset(row_offset)
        .limit(row_limit)
        .all()
    )

    detail = CallImportDetailResponse.model_validate(call_import)
    detail.rows = [CallImportRowResponse.model_validate(r) for r in rows]
    return detail


def _revoke_pending_tasks(rows: List[CallImportRow]) -> None:
    """Best-effort revoke of in-flight Celery tasks for the given rows.

    Failures are logged and swallowed — Celery's control plane is async and
    best-effort by design, and we always do an idempotent S3 cleanup
    afterwards so a missed revoke can't leak storage.
    """
    task_ids = [
        r.celery_task_id
        for r in rows
        if r.celery_task_id
        and r.status in (CallImportRowStatus.PENDING, CallImportRowStatus.PROCESSING)
    ]
    if not task_ids:
        return

    try:
        from app.workers.celery_app import celery_app

        celery_app.control.revoke(task_ids, terminate=False)
        logger.info("Revoked {} pending call-import tasks", len(task_ids))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to revoke pending call-import tasks: {}", exc)


def _delete_s3_objects(
    organization_id: UUID,
    call_import_id: UUID,
    rows: List[CallImportRow],
) -> tuple[int, int]:
    """Delete every recording associated with ``rows`` plus a prefix sweep.

    Returns ``(deleted_count, error_count)``. Never raises — callers proceed
    with the DB delete regardless; orphans, if any, can be cleaned up by
    re-running the same delete (it's idempotent).
    """
    from app.services.storage.s3_service import s3_service

    if not s3_service.is_enabled():
        return 0, 0

    keys = [r.recording_s3_key for r in rows if r.recording_s3_key]
    deleted = 0
    errors = 0

    if keys:
        try:
            d, errs = s3_service.delete_keys(keys)
            deleted += d
            errors += len(errs)
            if errs:
                logger.warning(
                    "S3 bulk-delete reported {} errors for call_import {}",
                    len(errs),
                    call_import_id,
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Bulk S3 delete failed for call_import {}: {}", call_import_id, exc
            )
            errors += len(keys)

    # Belt-and-braces sweep: catch anything that landed under the import's
    # prefix but never made it into a row's recording_s3_key (narrow
    # window where the S3 upload succeeded but the DB commit didn't).
    sweep_prefix = (
        f"{s3_service.prefix}organizations/{organization_id}/"
        f"call_imports/{call_import_id}/"
    )
    try:
        d, errs = s3_service.delete_keys_by_prefix(sweep_prefix)
        deleted += d
        errors += len(errs)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "S3 prefix sweep failed for {}: {}", sweep_prefix, exc
        )

    return deleted, errors


@router.delete(
    "/{call_import_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteCallImport",
)
async def delete_call_import(
    call_import_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> Response:
    """Delete a call-import batch, its rows, and every associated S3 recording.

    Idempotent and safe to retry. If the batch is still in flight we revoke
    pending Celery tasks before tearing down the rows so workers can't
    write back to deleted records.
    """

    call_import = (
        db.query(CallImport)
        .filter(
            CallImport.id == call_import_id,
            CallImport.organization_id == organization_id,
        )
        .first()
    )
    if not call_import:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call import not found",
        )

    rows = (
        db.query(CallImportRow)
        .filter(CallImportRow.call_import_id == call_import.id)
        .all()
    )

    _revoke_pending_tasks(rows)

    deleted_objects, s3_errors = _delete_s3_objects(
        organization_id=organization_id,
        call_import_id=call_import.id,
        rows=rows,
    )

    db.delete(call_import)  # cascades to call_import_rows
    db.commit()

    logger.info(
        "Deleted call_import {} (org={}, rows={}, s3_objects_deleted={}, s3_errors={})",
        call_import.id,
        organization_id,
        len(rows),
        deleted_objects,
        s3_errors,
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{call_import_id}/rows/{row_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteCallImportRow",
)
async def delete_call_import_row(
    call_import_id: UUID,
    row_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> Response:
    """Delete a single CallImportRow and its S3 recording.

    The parent ``CallImport`` is left in place. After deletion we recompute
    its ``total_rows`` / ``completed_rows`` / ``failed_rows`` / ``status``
    so the UI's progress bar stays consistent with reality.
    """
    from app.services.storage.s3_service import s3_service

    call_import = (
        db.query(CallImport)
        .filter(
            CallImport.id == call_import_id,
            CallImport.organization_id == organization_id,
        )
        .first()
    )
    if not call_import:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call import not found",
        )

    row = (
        db.query(CallImportRow)
        .filter(
            CallImportRow.id == row_id,
            CallImportRow.call_import_id == call_import.id,
        )
        .first()
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call import row not found",
        )

    _revoke_pending_tasks([row])

    if row.recording_s3_key and s3_service.is_enabled():
        try:
            s3_service.delete_file_by_key(row.recording_s3_key)
        except Exception as exc:  # noqa: BLE001 — best-effort, DB is source of truth
            logger.warning(
                "Failed to delete S3 object {} for row {}: {}",
                row.recording_s3_key,
                row.id,
                exc,
            )

    db.delete(row)
    db.flush()

    # Recompute parent counters/status from what's left.
    remaining = (
        db.query(CallImportRow)
        .filter(CallImportRow.call_import_id == call_import.id)
        .all()
    )
    completed = sum(1 for r in remaining if r.status == CallImportRowStatus.COMPLETED)
    failed = sum(1 for r in remaining if r.status == CallImportRowStatus.FAILED)
    pending_or_processing = sum(
        1
        for r in remaining
        if r.status in (CallImportRowStatus.PENDING, CallImportRowStatus.PROCESSING)
    )

    call_import.total_rows = len(remaining)
    call_import.completed_rows = completed
    call_import.failed_rows = failed
    if pending_or_processing > 0:
        call_import.status = CallImportStatus.PROCESSING
    elif len(remaining) == 0:
        # No rows left — leave the batch in its current terminal status
        # rather than synthesizing a misleading "completed". The user can
        # delete the empty batch from the UI if they want it gone.
        pass
    elif failed == 0:
        call_import.status = CallImportStatus.COMPLETED
    elif completed == 0:
        call_import.status = CallImportStatus.FAILED
    else:
        call_import.status = CallImportStatus.PARTIAL

    db.commit()

    logger.info(
        "Deleted call_import_row {} (call_import={}, org={})",
        row_id,
        call_import.id,
        organization_id,
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
