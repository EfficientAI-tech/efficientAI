"""CSV-driven call import routes (package)."""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, BackgroundTasks, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from loguru import logger
from sqlalchemy import desc, func, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.core.auth import Principal, get_principal
from app.core.auth.rbac import require_admin
from app.database import get_db
from app.db_sharding.sessions import is_sharding_enabled
from app.dependencies import (
    get_api_key,
    get_organization_id,
    get_workspace_id,
    require_enterprise_feature,
)
from app.services.billing.flexprice_service import record_call_import_batch_created
from app.services.call_imports.audit import (
    actor_emails_for_call_import,
    emails_for_user_ids,
    stamp_call_import_actor,
    user_ids_from_call_imports,
)
from app.services.call_imports import import_queries as call_import_queries
from app.services.call_imports.import_queries import (
    locate_call_import_row_or_404 as _locate_call_import_row_or_404,
)
from app.services.call_imports.import_row_mutations import (
    bulk_delete_call_import_rows as _bulk_delete_call_import_rows,
    delete_call_import as _delete_call_import_service,
    delete_call_import_row as _delete_call_import_row_service,
    delete_s3_objects as _delete_s3_objects,
    recompute_call_import_counters as _recompute_call_import_counters,
    retry_failed_call_import_rows as _retry_failed_call_import_rows,
    revoke_pending_tasks as _revoke_pending_tasks,
    start_legacy_call_import as _start_legacy_call_import,
)
from app.services.call_imports import diarisation_route_helpers as diarisation_helpers
from app.services.call_imports import manual_audio_route_helpers as manual_audio_helpers
from app.services.call_imports import present as call_import_present
from app.services.call_imports import source_parse as call_import_source_parse
from app.models.database import (
    CallImport,
    CallImportRow,
    CallImportSchema,
    CallImportSchemaParameter,
    CallImportTag,
    TelephonyIntegration,
)
from app.models.enums import (
    CallImportParameterType,
    CallImportRowStatus,
    CallImportStatus,
)
from app.models.schemas import (
    CallImportCancelDiarisationRequest,
    CallImportCancelDiarisationResponse,
    CallImportDetailResponse,
    CallImportDeleteResponse,
    CallImportDiarisationPromptDefaultResponse,
    CallImportDispatchDiagnosticsResponse,
    CallImportInsightsMetric,
    CallImportInsightsResponse,
    CallImportInsightsRunPoint,
    CallImportListResponse,
    CallImportMappingUpdate,
    CallImportManualAudioCompleteRequest,
    CallImportManualAudioCompleteResponse,
    CallImportManualAudioPresignRequest,
    CallImportManualAudioPresignResponse,
    CallImportManualAudioPresignUploadItem,
    CallImportMetricAggregate,
    CallImportPreviewResponse,
    CallImportPreviewSheet,
    CallImportRetryFailedRowsRequest,
    CallImportRetryFailedRowsResponse,
    CallImportResponse,
    CallImportRowIdsResponse,
    CallImportRowBulkDelete,
    CallImportRowBulkDeleteResponse,
    CallImportRowResponse,
    CallImportStartRequest,
    CallImportSourceStageCompleteRequest,
    CallImportSourceStagePresignRequest,
    CallImportSourceStagePresignResponse,
    CallImportTranscribeRequest,
    CallImportTranscribeResponse,
    CallImportUpdate,
    CallImportUploadResponse,
    PlatformImportAgentRef,
)

from app.api.v1.routes.call_imports._router import router

CallImportParseSkip = call_import_source_parse.CallImportParseSkip
CallImportParseResult = call_import_source_parse.CallImportParseResult
parse_skips_to_json = call_import_source_parse.parse_skips_to_json
MAX_UPLOAD_BYTES = call_import_source_parse.MAX_UPLOAD_BYTES
CSV_EXTENSIONS = call_import_source_parse.CSV_EXTENSIONS
XLSX_EXTENSIONS = call_import_source_parse.XLSX_EXTENSIONS
ALLOWED_EXTENSIONS = call_import_source_parse.ALLOWED_EXTENSIONS
_file_format = call_import_source_parse._file_format
_normalize_header = call_import_source_parse._normalize_header
_parse_csv = call_import_source_parse._parse_csv
_parse_xlsx = call_import_source_parse._parse_xlsx
_parse_recording_date_cell = call_import_source_parse._parse_recording_date_cell
_parse_source_file = call_import_source_parse._parse_source_file
_apply_schema_mapping = call_import_source_parse._apply_schema_mapping
_clean_parameter_mapping = call_import_source_parse._clean_parameter_mapping
_clean_skipped_columns = call_import_source_parse._clean_skipped_columns
_resolve_schema = call_import_source_parse._resolve_schema
_validate_sheet_choice = call_import_source_parse._validate_sheet_choice
_source_s3_key = call_import_source_parse._source_s3_key
_source_content_type = call_import_source_parse._source_content_type
_build_available_sheets = call_import_source_parse._build_available_sheets
_csv_preview_sheets = call_import_source_parse._csv_preview_sheets
_xlsx_preview_sheets = call_import_source_parse._xlsx_preview_sheets
_insert_staged_call_import_record = call_import_source_parse._insert_staged_call_import_record
_parse_json_form_field = call_import_source_parse._parse_json_form_field
_raise_if_no_importable_rows = call_import_source_parse._raise_if_no_importable_rows
_parameter_is_required = call_import_source_parse._parameter_is_required

_normalize_dataset = call_import_present._normalize_dataset
_normalize_import_display_name = call_import_present._normalize_import_display_name
_imported_agent_partial_id = call_import_present._imported_agent_partial_id
_platform_agent_refs = call_import_present._platform_agent_refs
_remember_platform_agent_names = call_import_present._remember_platform_agent_names
_serialize_call_import = call_import_present._serialize_call_import
_resolve_tags = call_import_present._resolve_tags
_tag_response_payload = call_import_present._tag_response_payload
_call_import_row_list_response = call_import_present._call_import_row_list_response

MAX_AUDIO_FILES_PER_REQUEST = manual_audio_helpers.MAX_AUDIO_FILES_PER_REQUEST
_enforce_audio_upload_file_limit = manual_audio_helpers._enforce_audio_upload_file_limit
_audio_extension = manual_audio_helpers._audio_extension
_audio_content_type = manual_audio_helpers._audio_content_type
_audio_s3_key = manual_audio_helpers._audio_s3_key
_manual_audio_append_start_state = manual_audio_helpers._manual_audio_append_start_state
_prepare_audio_upload_files = manual_audio_helpers._prepare_audio_upload_files
_prepare_audio_presign_items = manual_audio_helpers._prepare_audio_presign_items
_upload_manual_audio_blobs_parallel = manual_audio_helpers._upload_manual_audio_blobs_parallel
_persist_prepared_audio_rows = manual_audio_helpers._persist_prepared_audio_rows

CANCELLED_BY_USER_ERROR = diarisation_helpers.CANCELLED_BY_USER_ERROR
_cancellable_diarisation_states = diarisation_helpers._cancellable_diarisation_states
_revoke_diarisation_task = diarisation_helpers._revoke_diarisation_task
_apply_diarisation_cancel = diarisation_helpers._apply_diarisation_cancel
_render_diarised_segments_text = diarisation_helpers._render_diarised_segments_text

from app.services.call_imports.import_batch_helpers import (
    STUCK_PENDING_ERROR_MARKERS as _STUCK_PENDING_ERROR_MARKERS,
    ensure_blob_storage_enabled as _ensure_blob_storage_enabled,
    enqueue_row_tasks as _enqueue_row_tasks,
    is_manual_audio_call_import as _is_manual_audio_call_import,
    is_platform_call_import as _is_platform_call_import,
    is_stuck_pending_import_row as _is_stuck_pending_import_row,
    materialize_rows as _materialize_rows,
    normalize_content_modality as _normalize_content_modality,
    platform_import_hydration_complete,
    resolve_telephony_integration as _resolve_telephony_integration,
    validate_credentialed_import_ready as _validate_credentialed_import_ready,
    validate_diarised_eval_recording_ready as _validate_diarised_eval_recording_ready,
    validate_direct_url_import_ready as _validate_direct_url_import_ready,
    validate_exotel_import_ready as _validate_exotel_import_ready,
    validate_telephony_credentials_live as _validate_telephony_credentials_live,
)


@router.post(
    "/preview",
    response_model=CallImportPreviewResponse,
    operation_id="previewCallImportFile",
)
async def preview_call_import_file(
    file: UploadFile = File(...),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
) -> CallImportPreviewResponse:
    """Inspect an uploaded CSV / Excel file and return its sheets + headers.

    Drives the column-mapping UI without forcing the frontend to parse
    CSV / xlsx itself — keeps client and server in lockstep on quoted
    fields, encodings, and Excel cell coercion. CSVs return a single
    synthetic sheet named after the filename; Excel workbooks return one
    entry per worksheet (in workbook order).
    """
    del api_key, organization_id, workspace_id, db  # auth only

    fmt = _file_format(file.filename)
    if fmt is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Unsupported file format. Allowed extensions: "
                f"{', '.join(ALLOWED_EXTENSIONS)}."
            ),
        )

    file_bytes = await file.read()
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds {MAX_UPLOAD_BYTES} bytes",
        )

    if fmt == "csv":
        sheets = _csv_preview_sheets(file_bytes, file.filename)
    else:
        sheets = _xlsx_preview_sheets(file_bytes)

    return CallImportPreviewResponse(format=fmt, sheets=sheets)


@router.post(
    "/stage/presign",
    response_model=CallImportSourceStagePresignResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="presignCallImportSourceStage",
)
async def presign_call_import_source_stage(
    payload: CallImportSourceStagePresignRequest,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportSourceStagePresignResponse:
    del api_key, db
    _ensure_blob_storage_enabled()

    from app.services.call_imports import staged_source_presign as stage_mod
    from app.services.storage.blob_storage_service import blob_storage_service

    fmt = stage_mod.validate_staged_source_file(
        payload.filename,
        payload.size_bytes,
        file_format=_file_format,
        max_upload_bytes=MAX_UPLOAD_BYTES,
    )
    normalized_dataset = _normalize_dataset(payload.dataset)
    if not normalized_dataset:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="dataset is required and must be a non-empty string.",
        )

    call_import_id = uuid4()
    content_type = _source_content_type(fmt)
    s3_key, upload_url = stage_mod.build_staged_source_presign(
        organization_id=organization_id,
        call_import_id=call_import_id,
        fmt=fmt,
        content_type=content_type,
        source_s3_key=_source_s3_key,
        generate_presigned_put_url_by_key=blob_storage_service.generate_presigned_put_url_by_key,
    )
    return CallImportSourceStagePresignResponse(
        call_import_id=call_import_id,
        source_s3_key=s3_key,
        source_format=fmt,
        upload_url=upload_url,
        content_type=content_type,
    )


@router.post(
    "/stage/complete",
    response_model=CallImportResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="completeCallImportSourceStage",
)
async def complete_call_import_source_stage(
    payload: CallImportSourceStageCompleteRequest,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> CallImportResponse:
    del api_key
    _ensure_blob_storage_enabled()

    from app.services.call_imports import staged_source_presign as stage_mod
    from app.services.storage.blob_storage_service import blob_storage_service

    fmt = stage_mod.validate_staged_source_file(
        payload.filename,
        payload.size_bytes,
        file_format=_file_format,
        max_upload_bytes=MAX_UPLOAD_BYTES,
    )
    normalized_dataset = _normalize_dataset(payload.dataset)
    if not normalized_dataset:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="dataset is required and must be a non-empty string.",
        )
    normalized_modality = _normalize_content_modality(payload.content_modality)
    if payload.schema_id is not None:
        _resolve_schema(db, organization_id, workspace_id, payload.schema_id)
    tag_rows = _resolve_tags(db, organization_id, payload.tag_ids)

    s3_key = _source_s3_key(organization_id, payload.call_import_id, fmt)
    content_type = _source_content_type(fmt)

    try:
        file_bytes = stage_mod.load_staged_source_bytes(
            source_s3_key=s3_key,
            expected_size=payload.size_bytes,
            head_object_by_key=blob_storage_service.head_object_by_key,
            download_file_by_key=blob_storage_service.download_file_by_key,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "Failed to load staged source from S3 for call import {}",
            payload.call_import_id,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to read staged upload from storage: {exc}",
        ) from exc

    existing = (
        db.query(CallImport)
        .filter(
            CallImport.id == payload.call_import_id,
            CallImport.organization_id == organization_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This staged import id is already registered.",
        )

    try:
        call_import = _insert_staged_call_import_record(
            db,
            call_import_id=payload.call_import_id,
            organization_id=organization_id,
            workspace_id=workspace_id,
            principal=principal,
            filename=payload.filename,
            fmt=fmt,
            s3_key=s3_key,
            content_type=content_type,
            file_bytes=file_bytes,
            normalized_dataset=normalized_dataset,
            schema_id=payload.schema_id,
            normalized_modality=normalized_modality,
            tag_rows=tag_rows,
        )
    except Exception:
        db.rollback()
        raise

    return _serialize_call_import(db, call_import)


@router.post(
    "",
    response_model=CallImportResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createCallImport",
    deprecated=True,
)
async def create_call_import(
    file: UploadFile = File(
        ...,
        description="CSV / Excel file to stage. Persisted to S3 between stages.",
    ),
    dataset: str = Form(
        ...,
        description=(
            "Required free-text dataset label. Collected up-front so the "
            "batch is filterable from the moment it lands."
        ),
    ),
    tag_ids: Optional[List[UUID]] = Form(
        None,
        description="Optional list of CallImportTag ids to attach to the new batch.",
    ),
    schema_id: Optional[UUID] = Form(
        None,
        description=(
            "Optional schema pre-pick. The user can still change it during "
            "the MAP stage; provided here only so the detail page can pre-"
            "select the schema dropdown."
        ),
    ),
    content_modality: Optional[str] = Form(
        None,
        description="Optional 'chat' for transcript-only post-prod chat imports; omit for voice/call imports.",
    ),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> CallImportResponse:
    """UPLOAD stage (legacy multipart).

    Prefer ``POST /stage/presign`` then browser PUT then ``POST /stage/complete``
    so the API never buffers the source file.
    """
    del api_key

    fmt = _file_format(file.filename)
    if fmt is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Unsupported file format. Allowed extensions: "
                f"{', '.join(ALLOWED_EXTENSIONS)}."
            ),
        )

    normalized_dataset = _normalize_dataset(dataset)
    if not normalized_dataset:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="dataset is required and must be a non-empty string.",
        )

    file_bytes = await file.read()
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds {MAX_UPLOAD_BYTES} bytes",
        )

    if schema_id is not None:
        _resolve_schema(db, organization_id, workspace_id, schema_id)

    normalized_modality = _normalize_content_modality(content_modality)
    tag_rows = _resolve_tags(db, organization_id, tag_ids)

    _ensure_blob_storage_enabled()

    call_import_id = uuid4()
    s3_key = _source_s3_key(organization_id, call_import_id, fmt)
    content_type = _source_content_type(fmt)

    from app.services.storage.s3_service import s3_service, StorageError

    try:
        s3_service.upload_file_by_key(file_bytes, s3_key, content_type=content_type)
    except StorageError as exc:
        logger.exception(
            "Failed to upload source file to S3 for new call import {}",
            call_import_id,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to persist upload to S3: {exc}",
        )

    try:
        call_import = _insert_staged_call_import_record(
            db,
            call_import_id=call_import_id,
            organization_id=organization_id,
            workspace_id=workspace_id,
            principal=principal,
            filename=file.filename or "upload.csv",
            fmt=fmt,
            s3_key=s3_key,
            content_type=content_type,
            file_bytes=file_bytes,
            normalized_dataset=normalized_dataset,
            schema_id=schema_id,
            normalized_modality=normalized_modality,
            tag_rows=tag_rows,
        )
    except Exception:
        db.rollback()
        try:
            s3_service.delete_file_by_key(s3_key)
        except Exception as cleanup_exc:  # noqa: BLE001
            logger.warning(
                "Failed to clean up orphaned S3 object {} after DB rollback: {}",
                s3_key,
                cleanup_exc,
            )
        raise

    return _serialize_call_import(db, call_import)


@router.patch(
    "/{call_import_id}/mapping",
    response_model=CallImportResponse,
    operation_id="updateCallImportMapping",
)
async def update_call_import_mapping(
    call_import_id: UUID,
    payload: CallImportMappingUpdate,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> CallImportResponse:
    """MAP stage of the staged call-import flow.

    Validates ``parameter_mapping`` + ``skipped_columns`` against the
    sheet headers captured at UPLOAD time and persists them on the
    batch. Idempotent: callers may submit this multiple times while
    the batch is in ``uploaded`` or ``mapped`` state.
    """
    del api_key

    call_import = (
        db.query(CallImport)
        .filter(
            CallImport.id == call_import_id,
            CallImport.organization_id == organization_id,
            CallImport.workspace_id == workspace_id,
        )
        .first()
    )
    if not call_import:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call import not found",
        )

    if call_import.status not in (
        CallImportStatus.UPLOADED,
        CallImportStatus.MAPPED,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot edit mapping on a batch in status "
                f"'{call_import.status.value}'. Mapping can only be edited "
                "before the IMPORT stage."
            ),
        )

    if not call_import.source_s3_key or not call_import.source_format:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This batch was not uploaded through the staged flow and "
                "cannot have its mapping edited."
            ),
        )

    schema = _resolve_schema(
        db, organization_id, workspace_id, payload.schema_id
    )
    parameters = list(schema.parameters)

    canonical_sheet = _validate_sheet_choice(
        call_import.source_format,
        payload.sheet_name,
        call_import.available_sheets,
    )

    # Pull the headers for the selected sheet straight out of the
    # snapshot so we don't have to re-download the file from S3 just to
    # validate the mapping.
    headers: List[str] = []
    if call_import.available_sheets:
        if canonical_sheet is None:
            # CSV: single synthetic sheet.
            entry = call_import.available_sheets[0]
            headers = list(entry.get("headers") or [])
        else:
            for entry in call_import.available_sheets:
                if not isinstance(entry, dict):
                    continue
                name = entry.get("name")
                if isinstance(name, str) and name == canonical_sheet:
                    headers = list(entry.get("headers") or [])
                    break

    cleaned_mapping = _clean_parameter_mapping(
        payload.parameter_mapping, parameters, schema.name
    )
    cleaned_skipped = _clean_skipped_columns(payload.skipped_columns)

    # Run the same per-column validation as the parse path so the user
    # gets an immediate 400 if a required parameter is left unmapped or
    # a header is neither mapped nor skipped — without needing to read
    # the file. ``validate_only`` skips the row loop (and the empty-rows
    # guard) since the row data lives in S3, not in this request.
    if headers:
        _apply_schema_mapping(
            headers,
            iter(()),
            parameters,
            cleaned_mapping,
            cleaned_skipped,
            source_label=(
                f"Sheet '{canonical_sheet}'"
                if canonical_sheet is not None
                else "CSV"
            ),
            validate_only=True,
        )

    call_import.schema_id = schema.id
    call_import.parameter_mapping = dict(cleaned_mapping)
    call_import.skipped_columns = list(cleaned_skipped)
    call_import.sheet_name = canonical_sheet
    call_import.status = CallImportStatus.MAPPED
    stamp_call_import_actor(call_import, principal)
    db.commit()
    db.refresh(call_import)
    return _serialize_call_import(db, call_import)


@router.post(
    "/{call_import_id}/import",
    response_model=CallImportUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="startCallImport",
)
async def start_call_import(
    call_import_id: UUID,
    payload: CallImportStartRequest,
    background_tasks: BackgroundTasks,
    legacy: bool = Query(
        False,
        description=(
            "Deprecated escape hatch for import-only processing. "
            "New batches should use Run Evaluation instead."
        ),
    ),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> CallImportUploadResponse:
    """Deprecated IMPORT stage — use Run Evaluation for new batches.

    Recording fetch is part of the unified evaluation pipeline. This
    endpoint remains available only with ``?legacy=true`` for backward
    compatibility.
    """
    del api_key, background_tasks

    if not legacy:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Standalone import is deprecated. Use Run Evaluation — "
                "recording fetch is part of the evaluation pipeline. "
                "Append ?legacy=true to use the import-only path."
            ),
        )

    return _start_legacy_call_import(
        db,
        call_import_id,
        organization_id,
        workspace_id,
        principal,
        payload,
    )


@router.post(
    "/upload",
    status_code=status.HTTP_410_GONE,
    operation_id="uploadCallImportCsv",
    deprecated=True,
)
async def upload_call_import_csv_removed() -> None:
    """Removed: use staged presign then MAP/IMPORT."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "POST /call-imports/upload was removed. Stage the CSV with "
            "POST /call-imports/stage/presign and POST /call-imports/stage/complete, "
            "then PATCH /{id}/mapping and POST /{id}/import?legacy=true."
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
    source_format: Optional[str] = Query(
        None,
        description=(
            "Filter by source format. Use 'audio' for manual recordings or "
            "'__non_audio__' for CSV/Excel/legacy imports."
        ),
    ),
    content_modality: Optional[str] = Query(
        None,
        description="Filter by content_modality (e.g. 'chat'). Use '__voice__' for non-chat batches.",
    ),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
) -> CallImportListResponse:
    """List call-import batches for the active workspace, newest first.

    Scoped to (organization_id, workspace_id) so users only see imports
    for the workspace they're currently in. Supports a high-level
    ``dataset`` filter (powers the segregation dropdown at the top of
    the imports page) plus an AND-style multi-tag filter via repeated
    ``tag_id`` parameters.
    """
    del api_key
    return call_import_queries.list_call_imports_page(
        db,
        organization_id,
        workspace_id,
        page=page,
        page_size=page_size,
        status_filter=status_filter,
        dataset=dataset,
        tag_id=tag_id,
        source_format=source_format,
        content_modality=content_modality,
    )


@router.get(
    "/dispatch-diagnostics",
    response_model=CallImportDispatchDiagnosticsResponse,
    operation_id="getCallImportDispatchDiagnostics",
    dependencies=[Depends(require_admin)],
)
async def get_call_import_dispatch_diagnostics(
    workspace_id: Optional[UUID] = Query(
        None,
        description=(
            "Optional workspace filter. When omitted, returns every workspace "
            "in the organization with active eval dispatch state."
        ),
    ),
    include_idle_workspaces: bool = Query(
        False,
        description=(
            "When true, include org workspaces with zero pending rows and "
            "zero in-flight slots."
        ),
    ),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportDispatchDiagnosticsResponse:
    """Live eval slot usage and fair-dispatch state for operators.

    Org admins use this to diagnose cross-workspace starvation (e.g. one
    workspace's 10k run blocking another's pending eval rows) by inspecting
    Redis in-flight counters, pending dispatch rows, and scheduler cursors.
    """
    del api_key
    payload = call_import_queries.get_call_import_dispatch_diagnostics_payload(
        db,
        organization_id,
        workspace_id=workspace_id,
        include_idle_workspaces=include_idle_workspaces,
    )
    return CallImportDispatchDiagnosticsResponse.model_validate(payload)


@router.get(
    "/datasets",
    response_model=List[str],
    operation_id="listCallImportDatasets",
)
async def list_call_import_datasets(
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
) -> List[str]:
    """Return the distinct, non-null dataset labels in use for the active
    workspace.

    Scoped per-workspace so each workspace's Dataset dropdown only shows
    its own segregation labels.
    """
    del api_key
    return call_import_queries.list_call_import_dataset_labels(
        db, organization_id, workspace_id
    )


@router.get(
    "/diarisation-prompt-default",
    response_model=CallImportDiarisationPromptDefaultResponse,
    operation_id="getCallImportDiarisationPromptDefault",
)
async def get_call_import_diarisation_prompt_default(
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
) -> CallImportDiarisationPromptDefaultResponse:
    """Return the canonical LLM diariser prompt.

    The Transcribe / Run Evaluation modals call this on open so they
    can pre-fill the prompt textarea. Returning the constant from the
    backend (rather than hard-coding it in the frontend) keeps the
    fallback used by the worker and the placeholder shown in the UI
    in lock-step — operators always see the *actual* default they'd
    get if they leave the field blank.

    Registered before ``GET /{call_import_id}`` so the static path is
    not mistaken for a UUID import id (which would 422).
    """
    del api_key, organization_id
    from app.workers.tasks.helpers.llm_diarisation import (
        DEFAULT_DIARIZATION_PROMPT,
    )

    return CallImportDiarisationPromptDefaultResponse(
        prompt=DEFAULT_DIARIZATION_PROMPT
    )


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
    workspace_id: UUID = Depends(get_workspace_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> CallImportResponse:
    """Edit dataset / tag assignments (and schema, pre-import) on a batch.

    ``dataset = ""`` clears the label; ``tag_ids = []`` removes all tag
    assignments. Fields omitted from the body are left untouched.

    ``schema_id`` is only honoured while the batch is in
    ``uploaded`` / ``mapped`` state — once rows have been materialised
    the schema is locked. Changing the schema resets any persisted
    mapping (the user must re-MAP) and rewinds status to ``uploaded``.
    """
    del api_key

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
    if "original_filename" in body:
        call_import.original_filename = _normalize_import_display_name(
            body["original_filename"]
        )

    if "dataset" in body:
        call_import.dataset = _normalize_dataset(body["dataset"])

    if "tag_ids" in body:
        tag_ids = body["tag_ids"] or []
        call_import.tags = _resolve_tags(db, organization_id, tag_ids)

    if "schema_id" in body and body["schema_id"] is not None:
        if call_import.status not in (
            CallImportStatus.UPLOADED,
            CallImportStatus.MAPPED,
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot reassign schema on a batch in status "
                    f"'{call_import.status.value}'."
                ),
            )
        new_schema = _resolve_schema(
            db, organization_id, workspace_id, body["schema_id"]
        )
        if call_import.schema_id != new_schema.id:
            # Switching schemas invalidates the persisted mapping —
            # parameter names won't line up with the new schema, so
            # reset to UPLOADED and force a fresh MAP.
            call_import.schema_id = new_schema.id
            call_import.parameter_mapping = {}
            call_import.skipped_columns = []
            call_import.sheet_name = None
            call_import.status = CallImportStatus.UPLOADED

    stamp_call_import_actor(call_import, principal)
    db.commit()
    db.refresh(call_import)
    return _serialize_call_import(db, call_import)


@router.get(
    "/{call_import_id}",
    response_model=CallImportDetailResponse,
    operation_id="getCallImportDetail",
)
async def get_call_import_detail(
    call_import_id: UUID,
    row_limit: int = Query(500, ge=0, le=5000),
    row_offset: int = Query(0, ge=0),
    q: Optional[str] = Query(
        None,
        description=(
            "Optional case-insensitive substring filter on "
            "``conversation_id``. When set, ``filtered_total_rows`` in "
            "the response reflects the post-filter row count so the UI "
            "can paginate against the filtered slice."
        ),
    ),
    diarised_status: Optional[str] = Query(
        None,
        description=(
            "Optional filter on ``CallImportRow.diarised_transcript_status``. "
            "Accepts one of ``pending``, ``running``, ``completed``, "
            "``failed``. When set, ``filtered_total_rows`` reflects the "
            "post-filter row count (combined with the ``q`` filter when "
            "both are supplied) so the UI can paginate against the same "
            "slice it's displaying."
        ),
        pattern="^(pending|running|completed|failed)$",
    ),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportDetailResponse:
    """Fetch a single import batch with a slice of its rows.

    ``row_limit=0`` is intentionally allowed so callers that only need the
    batch metadata (e.g. the evaluation-detail page rendering the parent's
    column mapping) can skip the rows payload entirely.
    """
    del api_key
    return call_import_queries.get_call_import_detail(
        db,
        call_import_id,
        organization_id,
        row_limit=row_limit,
        row_offset=row_offset,
        q=q,
        diarised_status=diarised_status,
    )


@router.get(
    "/{call_import_id}/row-ids",
    response_model=CallImportRowIdsResponse,
    operation_id="listCallImportRowIds",
)
async def list_call_import_row_ids(
    call_import_id: UUID,
    q: Optional[str] = Query(
        None,
        description=(
            "Optional case-insensitive substring filter on "
            "``conversation_id``. Same semantics as the detail endpoint."
        ),
    ),
    diarised_status: Optional[str] = Query(
        None,
        description=(
            "Optional filter on ``CallImportRow.diarised_transcript_status``. "
            "Accepts ``pending`` / ``running`` / ``completed`` / ``failed``."
        ),
        pattern="^(pending|running|completed|failed)$",
    ),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportRowIdsResponse:
    """Return every matching ``CallImportRow.id`` for cross-page bulk select.

    Lightweight companion to ``GET /{call_import_id}`` — the detail
    endpoint caps ``row_limit`` at 5000 and ships the entire row body
    on each page, so harvesting ids that way is wasteful when the
    user just wants to bulk-delete or bulk-transcribe everything that
    matches the current filters. This endpoint applies the same ``q``
    and ``diarised_status`` filters and returns only the ids.
    """
    del api_key
    return call_import_queries.list_call_import_row_ids(
        db,
        call_import_id,
        organization_id,
        q=q,
        diarised_status=diarised_status,
    )

@router.delete(
    "/{call_import_id}",
    response_model=CallImportDeleteResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="deleteCallImport",
)
async def delete_call_import(
    call_import_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> CallImportDeleteResponse:
    """Delete a call-import batch asynchronously.

    Flips the batch to ``deleting`` and enqueues background teardown so
    large imports (thousands of rows + S3 objects) do not block the API.
    """
    del api_key
    return _delete_call_import_service(
        db, call_import_id, organization_id, principal
    )


@router.get(
    "/{call_import_id}/rows/{row_id}",
    response_model=CallImportRowResponse,
    operation_id="getCallImportRow",
)
async def get_call_import_row(
    call_import_id: UUID,
    row_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportRowResponse:
    """One import row, including transcript text omitted from the list."""
    del api_key
    return call_import_queries.get_call_import_row(
        db,
        call_import_id,
        row_id,
        organization_id,
    )


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
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> Response:
    """Delete a single CallImportRow and its S3 recording.

    The parent ``CallImport`` is left in place. After deletion we recompute
    its ``total_rows`` / ``completed_rows`` / ``failed_rows`` / ``status``
    so the UI's progress bar stays consistent with reality.
    """
    del api_key
    _delete_call_import_row_service(
        db, call_import_id, row_id, organization_id, principal
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{call_import_id}/retry-failed",
    response_model=CallImportRetryFailedRowsResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="retryFailedCallImportRows",
)
async def retry_failed_call_import_rows(
    call_import_id: UUID,
    payload: Optional[CallImportRetryFailedRowsRequest] = Body(None),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> CallImportRetryFailedRowsResponse:
    """Re-enqueue every failed import row in this batch.

    Useful when transient provider issues are resolved and the operator wants
    a one-click "try failed downloads again" pass without re-uploading the CSV.

    Pass ``provider`` + ``telephony_integration_id`` (or both omitted for
    direct-URL retry) to change how recordings are fetched on this pass.
    When the body is omitted entirely, the batch keeps its existing pinned
    credentials.
    """
    del api_key
    return _retry_failed_call_import_rows(
        db, call_import_id, organization_id, principal, payload
    )


@router.post(
    "/{call_import_id}/rows/bulk-delete",
    response_model=CallImportRowBulkDeleteResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="bulkDeleteCallImportRows",
)
async def bulk_delete_call_import_rows(
    call_import_id: UUID,
    payload: CallImportRowBulkDelete,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> CallImportRowBulkDeleteResponse:
    """Delete multiple ``CallImportRow`` rows in one request.

    Unknown / cross-tenant row ids are silently skipped — the response
    reports how many actually went away so a UI that holds onto stale
    ids (e.g. after another tab already deleted a row) doesn't 404
    the entire bulk action.
    """
    del api_key
    return _bulk_delete_call_import_rows(
        db, call_import_id, organization_id, principal, payload
    )


@router.get(
    "/{call_import_id}/insights",
    response_model=CallImportInsightsResponse,
    operation_id="getCallImportInsights",
)
async def get_call_import_insights(
    call_import_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportInsightsResponse:
    """Aggregate signals across every evaluation run on this import.

    Powers the Insights tab on the call-import detail page: returns
    per-metric "latest run" summaries plus a trend series of mean values
    across runs so the UI can render a small line chart per metric. Also
    bundles transcript coverage stats since those are the cheapest
    pre-eval health-check (e.g. "30 of 50 rows still missing
    transcripts").
    """

    del api_key
    return call_import_queries.build_call_import_insights(
        db, call_import_id, organization_id
    )

