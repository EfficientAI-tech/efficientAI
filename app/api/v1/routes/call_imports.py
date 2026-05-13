"""CSV-driven call import routes.

Users upload a CSV plus a per-batch column mapping (CSV header -> system
field). The backend persists a CallImport batch + one CallImportRow per
line, then fans the rows out to the Celery ``imports`` queue where each
row is downloaded using the telephony credential pinned on the batch.
When a row has no recording URL, the worker resolves it via the chosen
provider's call detail endpoint (Exotel today; Plivo CSVs must include
the URL).
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from loguru import logger
from pydantic import ValidationError
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_api_key, get_organization_id
from app.models.database import (
    CallImport,
    CallImportRow,
    CallImportTag,
    TelephonyIntegration,
)
from app.models.enums import (
    CallImportRowStatus,
    CallImportStatus,
)
from app.models.schemas import (
    CallImportColumnMapping,
    CallImportDetailResponse,
    CallImportListResponse,
    CallImportResponse,
    CallImportRowResponse,
    CallImportUpdate,
    CallImportUploadResponse,
)


router = APIRouter(prefix="/call-imports", tags=["Call Imports"])


def _normalize_dataset(raw: Optional[str]) -> Optional[str]:
    """Trim and treat empty strings as 'no dataset' (NULL)."""
    if raw is None:
        return None
    cleaned = raw.strip()
    return cleaned or None


def _resolve_tags(
    db: Session, organization_id: UUID, tag_ids: Optional[List[UUID]]
) -> List[CallImportTag]:
    """Look up tag rows by id, scoped to the organization.

    Raises HTTPException(400) if any id is unknown for the org.
    """
    if not tag_ids:
        return []
    rows = (
        db.query(CallImportTag)
        .filter(
            CallImportTag.organization_id == organization_id,
            CallImportTag.id.in_(tag_ids),
        )
        .all()
    )
    found_ids = {row.id for row in rows}
    missing = [str(tag_id) for tag_id in tag_ids if tag_id not in found_ids]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown call_import_tag id(s): {missing}",
        )
    return rows


MAX_CSV_BYTES = 10 * 1024 * 1024  # 10 MB CSV cap


def _normalize_header(name: str) -> str:
    return (name or "").strip().lower()


def _header_lookup(fieldnames: List[str]) -> Dict[str, str]:
    """Map normalized header -> original header for case-insensitive lookup."""
    return {_normalize_header(h): h for h in fieldnames or []}


def _resolve_mapped_header(
    mapping_value: Optional[str], header_lookup: Dict[str, str]
) -> Optional[str]:
    """Translate a user-supplied CSV header into the actual column key.

    The frontend sends headers exactly as they appear in the CSV, but we
    still normalize on the server so trailing whitespace / casing doesn't
    break matching. Returns the canonical fieldname or ``None`` if not
    present in the CSV.
    """
    if not mapping_value:
        return None
    return header_lookup.get(_normalize_header(mapping_value))


def _parse_csv(
    file_bytes: bytes,
    mapping: CallImportColumnMapping,
    extra_columns: List[str],
    custom_column_mapping: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Parse the CSV using ``mapping`` to find each system field.

    The returned list has one entry per non-empty row with:
      * ``external_call_id`` (str, required - row dropped with 400 if blank)
      * ``recording_url`` (Optional[str])
      * ``transcript`` (Optional[str])
      * ``raw_columns`` (Dict[str, str]) of the original row keyed by the
        uploader's headers, restricted to mapped + ``extra_columns``.
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

    header_lookup = _header_lookup(list(reader.fieldnames))
    callid_h = _resolve_mapped_header(mapping.external_call_id, header_lookup)
    if not callid_h:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"CSV does not contain the column '{mapping.external_call_id}' "
                "mapped to External Call ID."
            ),
        )
    transcript_h = _resolve_mapped_header(mapping.transcript, header_lookup)
    if mapping.transcript and transcript_h is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"CSV does not contain the column '{mapping.transcript}' mapped to Transcript.",
        )
    url_h = _resolve_mapped_header(mapping.recording_url, header_lookup)
    if mapping.recording_url and url_h is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"CSV does not contain the column '{mapping.recording_url}' "
                "mapped to Recording URL."
            ),
        )

    # Headers we must capture in raw_columns (mapped + extras + custom),
    # keyed by the canonical CSV fieldname so reads always work regardless
    # of case. Custom-mapped CSV headers are validated the same way as the
    # system fields so a typo surfaces as a 400 rather than a silent drop.
    custom_mapping = custom_column_mapping or {}
    for custom_name, custom_header in custom_mapping.items():
        canonical = _resolve_mapped_header(custom_header, header_lookup)
        if canonical is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"CSV does not contain the column '{custom_header}' "
                    f"mapped to custom field '{custom_name}'."
                ),
            )

    keep_canonical: Dict[str, str] = {}
    for raw_header in [
        mapping.external_call_id,
        mapping.transcript,
        mapping.recording_url,
        *extra_columns,
        *custom_mapping.values(),
    ]:
        canonical = _resolve_mapped_header(raw_header, header_lookup)
        if canonical:
            # Preserve user-facing label (uploader's casing) as the key.
            keep_canonical[canonical] = raw_header  # type: ignore[assignment]

    parsed: List[Dict[str, Any]] = []
    for idx, row in enumerate(reader):
        call_id = (row.get(callid_h) or "").strip()
        url = (row.get(url_h) or "").strip() if url_h else ""
        transcript = (row.get(transcript_h) or "").strip() if transcript_h else ""
        # Fully blank line — skip silently to allow trailing newlines.
        if not any((row.get(h) or "").strip() for h in (callid_h, url_h, transcript_h) if h):
            continue
        if not call_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Row {idx + 1} is missing the External Call ID column.",
            )

        raw_snapshot = {
            label: (row.get(canonical) or "").strip()
            for canonical, label in keep_canonical.items()
        }

        parsed.append(
            {
                "external_call_id": call_id,
                "recording_url": url or None,
                "transcript": transcript or None,
                "raw_columns": raw_snapshot,
            }
        )

    if not parsed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV did not contain any data rows.",
        )

    return parsed


def _parse_json_form_field(name: str, raw: Optional[str], default):
    """Decode a JSON-encoded form field with a friendly 400 on bad JSON."""
    if raw is None or raw == "":
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{name} must be valid JSON: {exc}",
        )


@router.post(
    "/upload",
    response_model=CallImportUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="uploadCallImportCsv",
)
async def upload_call_import_csv(
    file: UploadFile = File(...),
    provider: str = Form(
        ...,
        description=(
            "Telephony provider key (e.g. 'exotel', 'plivo'). Must match the "
            "selected telephony_integration_id's provider."
        ),
    ),
    telephony_integration_id: UUID = Form(
        ...,
        description=(
            "Specific TelephonyIntegration credential row to use when "
            "downloading recordings for this batch."
        ),
    ),
    column_mapping: str = Form(
        ...,
        description=(
            "JSON-encoded mapping from system fields to CSV header strings. "
            "Required key: external_call_id. Optional: transcript, recording_url."
        ),
    ),
    extra_columns: Optional[str] = Form(
        None,
        description=(
            "JSON-encoded list of additional CSV header strings to preserve "
            "verbatim into raw_columns for export."
        ),
    ),
    custom_column_mapping: Optional[str] = Form(
        None,
        description=(
            "JSON-encoded ``{custom_field_name: csv_header}`` map for "
            "uploader-defined columns. The CSV cells under each mapped "
            "header are preserved per row and surface under the chosen "
            "custom name in the evaluation export."
        ),
    ),
    dataset: Optional[str] = Form(
        None,
        description=(
            "Optional free-text dataset label for high-level segregation. "
            "Empty strings are stored as NULL."
        ),
    ),
    tag_ids: Optional[List[UUID]] = Form(
        None,
        description="Optional list of CallImportTag ids to attach to the new batch.",
    ),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportUploadResponse:
    """Accept a CSV + column mapping and queue per-row import jobs.

    The caller selects a specific telephony credential (so the worker uses
    *that* row to fetch recordings) and provides a column mapping so any
    CSV layout works. Unmapped headers can be preserved via ``extra_columns``
    so they ride along into the eventual evaluation export.
    """
    del api_key

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

    mapping_payload = _parse_json_form_field("column_mapping", column_mapping, {})
    try:
        mapping = CallImportColumnMapping.model_validate(mapping_payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid column_mapping: {exc.errors()}",
        )

    extras_payload = _parse_json_form_field("extra_columns", extra_columns, [])
    if not isinstance(extras_payload, list) or not all(
        isinstance(item, str) for item in extras_payload
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="extra_columns must be a JSON array of header strings.",
        )
    # Strip blanks and de-duplicate (case-insensitive) while preserving order.
    seen = set()
    extras_clean: List[str] = []
    for item in extras_payload:
        norm = _normalize_header(item)
        if not norm or norm in seen:
            continue
        # Skip extras that collide with mapped fields - already captured.
        if norm in {
            _normalize_header(mapping.external_call_id),
            _normalize_header(mapping.transcript or ""),
            _normalize_header(mapping.recording_url or ""),
        }:
            continue
        seen.add(norm)
        extras_clean.append(item)

    custom_payload = _parse_json_form_field(
        "custom_column_mapping", custom_column_mapping, {}
    )
    if not isinstance(custom_payload, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in custom_payload.items()
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="custom_column_mapping must be a JSON object of {name: csv_header}.",
        )
    system_field_names = {"external_call_id", "transcript", "recording_url"}
    custom_clean: Dict[str, str] = {}
    seen_custom_names: set[str] = set()
    for raw_name, raw_header in custom_payload.items():
        name = raw_name.strip()
        header = raw_header.strip()
        if not name or not header:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "custom_column_mapping entries must have non-empty "
                    "name and CSV header values."
                ),
            )
        if name in system_field_names:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Custom column name '{name}' collides with a built-in "
                    "system field. Use a different name."
                ),
            )
        if name.lower() in seen_custom_names:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Duplicate custom column name '{name}'.",
            )
        seen_custom_names.add(name.lower())
        custom_clean[name] = header

    integration = (
        db.query(TelephonyIntegration)
        .filter(
            TelephonyIntegration.id == telephony_integration_id,
            TelephonyIntegration.organization_id == organization_id,
        )
        .first()
    )
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Telephony credential not found for this organization.",
        )
    if (integration.provider or "").lower() != provider.lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Selected credential is for provider '{integration.provider}', "
                f"but request specified '{provider}'."
            ),
        )
    if not integration.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Selected telephony credential is inactive.",
        )

    rows = _parse_csv(file_bytes, mapping, extras_clean, custom_clean)

    tag_rows = _resolve_tags(db, organization_id, tag_ids)

    stored_mapping = {
        "external_call_id": mapping.external_call_id,
        "transcript": mapping.transcript,
        "recording_url": mapping.recording_url,
    }

    call_import = CallImport(
        organization_id=organization_id,
        provider=integration.provider,
        telephony_integration_id=integration.id,
        original_filename=file.filename,
        dataset=_normalize_dataset(dataset),
        column_mapping=stored_mapping,
        extra_columns=extras_clean,
        custom_column_mapping=custom_clean,
        total_rows=len(rows),
        completed_rows=0,
        failed_rows=0,
        status=CallImportStatus.PENDING,
    )
    if tag_rows:
        call_import.tags = tag_rows
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
            raw_columns=row["raw_columns"] or None,
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
        dataset=call_import.dataset,
        tags=[
            {
                "id": tag.id,
                "name": tag.name,
                "color": tag.color,
                "created_at": tag.created_at,
                "updated_at": tag.updated_at,
            }
            for tag in (call_import.tags or [])
        ],
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
    dataset: Optional[str] = Query(
        None,
        description=(
            "Filter by exact dataset string (case-insensitive). Pass the "
            "literal value '__none__' to filter to imports with no dataset."
        ),
    ),
    tag_id: Optional[List[UUID]] = Query(
        None,
        description="Filter to imports tagged with ALL of the given tag ids.",
    ),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportListResponse:
    """List call-import batches for the organization, newest first.

    Supports a high-level ``dataset`` filter (powers the segregation
    dropdown at the top of the imports page) plus an AND-style multi-tag
    filter via repeated ``tag_id`` parameters.
    """

    query = db.query(CallImport).filter(CallImport.organization_id == organization_id)
    if status_filter is not None:
        query = query.filter(CallImport.status == status_filter)

    if dataset is not None:
        if dataset == "__none__":
            query = query.filter(CallImport.dataset.is_(None))
        elif dataset.strip():
            query = query.filter(
                func.lower(CallImport.dataset) == dataset.strip().lower()
            )

    if tag_id:
        from app.models.database import CallImportTagAssignment

        for single_tag_id in tag_id:
            sub = (
                db.query(CallImportTagAssignment.call_import_id)
                .filter(CallImportTagAssignment.tag_id == single_tag_id)
                .subquery()
            )
            query = query.filter(CallImport.id.in_(sub))

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
    "/datasets",
    response_model=List[str],
    operation_id="listCallImportDatasets",
)
async def list_call_import_datasets(
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> List[str]:
    """Return the distinct, non-null dataset labels in use for this org.

    Powers the high-level Dataset dropdown at the top of the call imports
    page.
    """
    rows = (
        db.query(CallImport.dataset)
        .filter(
            CallImport.organization_id == organization_id,
            CallImport.dataset.isnot(None),
            CallImport.dataset != "",
        )
        .distinct()
        .order_by(CallImport.dataset.asc())
        .all()
    )
    return [row[0] for row in rows if row[0]]


@router.patch(
    "/{call_import_id}",
    response_model=CallImportResponse,
    operation_id="updateCallImport",
)
async def update_call_import(
    call_import_id: UUID,
    payload: CallImportUpdate,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportResponse:
    """Edit dataset / tag assignments on an existing call-import batch.

    ``dataset = ""`` clears the label; ``tag_ids = []`` removes all tag
    assignments. Fields omitted from the body are left untouched.
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

    body = payload.model_dump(exclude_unset=True)
    if "dataset" in body:
        call_import.dataset = _normalize_dataset(body["dataset"])

    if "tag_ids" in body:
        tag_ids = body["tag_ids"] or []
        call_import.tags = _resolve_tags(db, organization_id, tag_ids)

    db.commit()
    db.refresh(call_import)
    return CallImportResponse.model_validate(call_import)


@router.get(
    "/{call_import_id}",
    response_model=CallImportDetailResponse,
    operation_id="getCallImportDetail",
)
async def get_call_import_detail(
    call_import_id: UUID,
    row_limit: int = Query(500, ge=0, le=5000),
    row_offset: int = Query(0, ge=0),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportDetailResponse:
    """Fetch a single import batch with a slice of its rows.

    ``row_limit=0`` is intentionally allowed so callers that only need the
    batch metadata (e.g. the evaluation-detail page rendering the parent's
    column mapping) can skip the rows payload entirely.
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

    if row_limit == 0:
        rows: List[CallImportRow] = []
    else:
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
