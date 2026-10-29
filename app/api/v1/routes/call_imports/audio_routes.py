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
from app.services.call_imports.dispatch_diagnostics import (
    build_call_import_dispatch_diagnostics,
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

from app.api.v1.routes.call_imports.core_routes import (
    _audio_s3_key,
    _ensure_blob_storage_enabled,
    _enforce_audio_upload_file_limit,
    _manual_audio_append_start_state,
    _normalize_dataset,
    _normalize_import_display_name,
    _persist_prepared_audio_rows,
    _prepare_audio_presign_items,
    _prepare_audio_upload_files,
    _resolve_tags,
    _tag_response_payload,
)

@router.post(
    "/audio-upload/presign",
    response_model=CallImportManualAudioPresignResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="presignCallImportAudioUpload",
)
async def presign_call_import_audio_upload(
    payload: CallImportManualAudioPresignRequest,
    background_tasks: BackgroundTasks,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> CallImportManualAudioPresignResponse:
    del api_key
    _ensure_blob_storage_enabled()
    _enforce_audio_upload_file_limit(len(payload.files))

    normalized_dataset = _normalize_dataset(payload.dataset or "")
    if not normalized_dataset:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="dataset is required and must be a non-empty string.",
        )

    tag_rows = _resolve_tags(db, organization_id, payload.tag_ids)
    prepared = _prepare_audio_presign_items(payload.files, conversation_counts={})

    normalized_batch_name = _normalize_import_display_name(payload.batch_name)
    if normalized_batch_name:
        original_filename = normalized_batch_name
    elif len(prepared) == 1:
        original_filename = prepared[0]["filename"]
    else:
        original_filename = "Manual recordings"

    from app.services.call_imports import manual_audio_presign as presign_mod
    from app.services.storage.s3_service import s3_service

    call_import = CallImport(
        organization_id=organization_id,
        workspace_id=workspace_id,
        provider=None,
        telephony_integration_id=None,
        original_filename=original_filename,
        source_format="audio",
        source_size_bytes=0,
        source_content_type="audio/*",
        dataset=normalized_dataset,
        total_rows=0,
        completed_rows=0,
        failed_rows=0,
        status=CallImportStatus.COMPLETED,
    )
    if tag_rows:
        call_import.tags = tag_rows
    stamp_call_import_actor(call_import, principal, creating=True)

    try:
        db.add(call_import)
        db.flush()
        call_import.provider = None
        uploads_raw, _keys = presign_mod.build_manual_audio_presign_uploads(
            organization_id=organization_id,
            call_import_id=call_import.id,
            prepared=prepared,
            audio_s3_key=_audio_s3_key,
            generate_presigned_put_url_by_key=s3_service.generate_presigned_put_url_by_key,
        )
        presign_mod.persist_manual_audio_row_mappings(
            db,
            call_import=call_import,
            organization_id=organization_id,
            workspace_id=workspace_id,
            uploads=uploads_raw,
            start_row_index=0,
        )
        db.commit()
        if is_sharding_enabled():
            from app.db_sharding.registry import publish_slice_registry_change

            publish_slice_registry_change(call_import.id)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to presign manual call recording upload")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to prepare manual recording upload: {exc}",
        ) from exc

    db.refresh(call_import)
    background_tasks.add_task(
        record_call_import_batch_created,
        organization_id,
        call_import.id,
        workspace_id=workspace_id,
        total_rows=call_import.total_rows,
        source="audio",
        provider=None,
    )
    uploads = [
        CallImportManualAudioPresignUploadItem(
            row_id=item["row_id"],
            recording_s3_key=item["recording_s3_key"],
            conversation_id=item["conversation_id"],
            upload_url=item["upload_url"],
            content_type=item["content_type"],
            filename=item["filename"],
        )
        for item in uploads_raw
    ]
    return CallImportManualAudioPresignResponse(
        call_import_id=call_import.id,
        uploads=uploads,
        total_rows=call_import.total_rows,
        status=call_import.status,
        dataset=call_import.dataset,
        tags=_tag_response_payload(call_import.tags),
        message=(
            f"Presigned {len(uploads)} recording upload"
            f"{'' if len(uploads) == 1 else 's'}."
        ),
    )


@router.post(
    "/{call_import_id}/audio-append/presign",
    response_model=CallImportManualAudioPresignResponse,
    status_code=status.HTTP_200_OK,
    operation_id="presignAppendCallImportAudio",
)
async def presign_append_call_import_audio(
    call_import_id: UUID,
    payload: CallImportManualAudioPresignRequest,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
) -> CallImportManualAudioPresignResponse:
    del api_key
    _ensure_blob_storage_enabled()
    _enforce_audio_upload_file_limit(len(payload.files))

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
        raise HTTPException(status_code=404, detail="Call import not found")
    if (call_import.source_format or "").lower() != "audio":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Audio append is only supported for manual audio upload batches.",
        )
    if call_import.status != CallImportStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot append audio while batch is in status "
                f"'{call_import.status.value}'."
            ),
        )

    start_row_index, conversation_counts = _manual_audio_append_start_state(
        db, call_import
    )
    prepared = _prepare_audio_presign_items(payload.files, conversation_counts)

    from app.services.call_imports import manual_audio_presign as presign_mod
    from app.services.storage.s3_service import s3_service

    try:
        uploads_raw, _keys = presign_mod.build_manual_audio_presign_uploads(
            organization_id=organization_id,
            call_import_id=call_import.id,
            prepared=prepared,
            audio_s3_key=_audio_s3_key,
            generate_presigned_put_url_by_key=s3_service.generate_presigned_put_url_by_key,
        )
        presign_mod.persist_manual_audio_row_mappings(
            db,
            call_import=call_import,
            organization_id=organization_id,
            workspace_id=workspace_id,
            uploads=uploads_raw,
            start_row_index=start_row_index,
        )
        db.commit()
        if is_sharding_enabled():
            from app.db_sharding.registry import publish_slice_registry_change

            publish_slice_registry_change(call_import.id)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to presign manual audio append")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to prepare audio append: {exc}",
        ) from exc

    db.refresh(call_import)
    uploads = [
        CallImportManualAudioPresignUploadItem(
            row_id=item["row_id"],
            recording_s3_key=item["recording_s3_key"],
            conversation_id=item["conversation_id"],
            upload_url=item["upload_url"],
            content_type=item["content_type"],
            filename=item["filename"],
        )
        for item in uploads_raw
    ]
    return CallImportManualAudioPresignResponse(
        call_import_id=call_import.id,
        uploads=uploads,
        total_rows=call_import.total_rows,
        status=call_import.status,
        dataset=call_import.dataset,
        tags=_tag_response_payload(call_import.tags),
        message=(
            f"Presigned {len(uploads)} recording upload"
            f"{'' if len(uploads) == 1 else 's'} for append."
        ),
    )


@router.post(
    "/{call_import_id}/manual-audio/complete",
    response_model=CallImportManualAudioCompleteResponse,
    status_code=status.HTTP_200_OK,
    operation_id="completeCallImportManualAudioUpload",
)
async def complete_call_import_manual_audio_upload(
    call_import_id: UUID,
    payload: CallImportManualAudioCompleteRequest,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
) -> CallImportManualAudioCompleteResponse:
    del api_key
    _ensure_blob_storage_enabled()

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
        raise HTTPException(status_code=404, detail="Call import not found")

    from app.services.call_imports import manual_audio_presign as presign_mod
    from app.services.storage.s3_service import s3_service

    verified = presign_mod.verify_manual_audio_uploads(
        db,
        call_import_id=call_import.id,
        organization_id=organization_id,
        row_ids=payload.row_ids,
        head_object_by_key=s3_service.head_object_by_key,
    )
    db.commit()
    db.refresh(call_import)
    return CallImportManualAudioCompleteResponse(
        verified=verified,
        call_import_id=call_import.id,
        total_rows=int(call_import.total_rows or 0),
    )


@router.post(
    "/audio-upload",
    response_model=CallImportUploadResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="uploadCallImportAudio",
)
async def upload_call_import_audio(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(
        ...,
        description="One or more manual call recording audio files.",
    ),
    dataset: str = Form(
        ...,
        description="Required free-text dataset label for the manual upload batch.",
    ),
    tag_ids: Optional[List[UUID]] = Form(
        None,
        description="Optional list of CallImportTag ids to attach to the new batch.",
    ),
    batch_name: Optional[str] = Form(
        None,
        description=(
            "Optional display name for this manual upload batch. "
            "When omitted, a generic label is used for multi-file uploads."
        ),
    ),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> CallImportUploadResponse:
    """Persist manually uploaded recordings as completed CallImport rows.

    The rows skip the provider-download worker entirely because the audio
    bytes are already in hand. From this point onward they behave exactly
    like completed CSV-import rows: playback reads ``recording_s3_key`` and
    the existing diarisation/evaluation endpoints can operate on them.
    """

    normalized_dataset = _normalize_dataset(dataset)
    if not normalized_dataset:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="dataset is required and must be a non-empty string.",
        )

    _ensure_blob_storage_enabled()
    tag_rows = _resolve_tags(db, organization_id, tag_ids)
    prepared = await _prepare_audio_upload_files(files, conversation_counts={})

    normalized_batch_name = _normalize_import_display_name(batch_name)
    if normalized_batch_name:
        original_filename = normalized_batch_name
    elif len(prepared) == 1:
        original_filename = prepared[0]["filename"]
    else:
        original_filename = "Manual recordings"
    uploaded_keys: List[str] = []

    from app.services.storage.s3_service import s3_service

    call_import = CallImport(
        organization_id=organization_id,
        workspace_id=workspace_id,
        provider=None,
        telephony_integration_id=None,
        original_filename=original_filename,
        source_format="audio",
        source_size_bytes=0,
        source_content_type="audio/*",
        dataset=normalized_dataset,
        total_rows=0,
        completed_rows=0,
        failed_rows=0,
        status=CallImportStatus.COMPLETED,
    )
    if tag_rows:
        call_import.tags = tag_rows

    stamp_call_import_actor(call_import, principal, creating=True)
    try:
        db.add(call_import)
        db.flush()
        # The model's historical Python default is "exotel"; manual uploads
        # intentionally have no telephony provider.
        call_import.provider = None

        uploaded_keys = _persist_prepared_audio_rows(
            db,
            call_import=call_import,
            organization_id=organization_id,
            workspace_id=workspace_id,
            prepared=prepared,
            start_row_index=0,
        )
        db.commit()
        if is_sharding_enabled():
            from app.db_sharding.registry import publish_slice_registry_change

            publish_slice_registry_change(call_import.id)
    except Exception as exc:
        db.rollback()
        if uploaded_keys and s3_service.is_enabled():
            try:
                s3_service.delete_keys(uploaded_keys)
            except Exception:
                logger.exception(
                    "Failed to clean up manual audio upload keys after error"
                )
        logger.exception("Failed to persist manual call recording upload")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload manual recordings: {exc}",
        ) from exc

    db.refresh(call_import)
    background_tasks.add_task(
        record_call_import_batch_created,
        organization_id,
        call_import.id,
        workspace_id=workspace_id,
        total_rows=call_import.total_rows,
        source="audio",
        provider=None,
    )
    return CallImportUploadResponse(
        id=call_import.id,
        total_rows=call_import.total_rows,
        status=call_import.status,
        dataset=call_import.dataset,
        tags=_tag_response_payload(call_import.tags),
        message=(
            f"Uploaded {call_import.total_rows} manual recording"
            f"{'' if call_import.total_rows == 1 else 's'}."
        ),
    )


@router.post(
    "/{call_import_id}/audio-append",
    response_model=CallImportUploadResponse,
    status_code=status.HTTP_200_OK,
    operation_id="appendCallImportAudio",
)
async def append_call_import_audio(
    call_import_id: UUID,
    files: List[UploadFile] = File(
        ...,
        description="Additional manual call recording audio files for an existing batch.",
    ),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
) -> CallImportUploadResponse:
    """Append manually uploaded recordings to an existing audio batch."""

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
    if (call_import.source_format or "").lower() != "audio":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Audio append is only supported for manual audio upload batches.",
        )
    if call_import.status != CallImportStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot append audio while batch is in status "
                f"'{call_import.status.value}'."
            ),
        )

    _ensure_blob_storage_enabled()

    start_row_index, conversation_counts = _manual_audio_append_start_state(
        db,
        call_import,
    )

    prepared = await _prepare_audio_upload_files(files, conversation_counts)
    uploaded_keys: List[str] = []

    from app.services.storage.s3_service import s3_service

    try:
        uploaded_keys = _persist_prepared_audio_rows(
            db,
            call_import=call_import,
            organization_id=organization_id,
            workspace_id=workspace_id,
            prepared=prepared,
            start_row_index=start_row_index,
        )
        db.commit()
        if is_sharding_enabled():
            from app.db_sharding.registry import publish_slice_registry_change

            publish_slice_registry_change(call_import.id)
    except Exception as exc:
        db.rollback()
        if uploaded_keys and s3_service.is_enabled():
            try:
                s3_service.delete_keys(uploaded_keys)
            except Exception:
                logger.exception(
                    "Failed to clean up manual audio append keys after error"
                )
        logger.exception("Failed to append manual call recording upload")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to append manual recordings: {exc}",
        ) from exc

    db.refresh(call_import)
    return CallImportUploadResponse(
        id=call_import.id,
        total_rows=call_import.total_rows,
        status=call_import.status,
        dataset=call_import.dataset,
        tags=_tag_response_payload(call_import.tags),
        message=(
            f"Uploaded {len(prepared)} additional manual recording"
            f"{'' if len(prepared) == 1 else 's'} "
            f"({call_import.total_rows} total)."
        ),
    )

