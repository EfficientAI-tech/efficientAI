"""Write paths and orchestration for call-import batches and rows."""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy.orm import Session

from app.core.auth import Principal
from app.models.database import CallImport, CallImportRow
from app.models.enums import CallImportRowStatus, CallImportStatus
from app.models.schemas import (
    CallImportDeleteResponse,
    CallImportRetryFailedRowsRequest,
    CallImportRetryFailedRowsResponse,
    CallImportRowBulkDelete,
    CallImportRowBulkDeleteResponse,
    CallImportStartRequest,
    CallImportUploadResponse,
)
from app.services.call_imports.audit import stamp_call_import_actor
from app.services.call_imports.import_batch_helpers import (
    ensure_blob_storage_enabled,
    resolve_telephony_integration,
    validate_credentialed_import_ready,
    validate_direct_url_import_ready,
    validate_telephony_credentials_live,
)
from app.services.call_imports.import_queries import (
    get_call_import_for_org_or_404,
    locate_call_import_row_or_404,
)
from app.services.call_imports.present import _tag_response_payload
from app.services.call_imports.source_parse import _resolve_schema


def recompute_call_import_counters(db: Session, call_import: CallImport) -> None:
    from app.services.call_imports.bulk_ops import rollup_call_import_batch_status

    rollup_call_import_batch_status(db, call_import)


def revoke_pending_tasks(rows: List[CallImportRow]) -> None:
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


def delete_s3_objects(
    organization_id: UUID,
    call_import_id: UUID,
    rows: List[CallImportRow],
) -> tuple[int, int]:
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


def delete_call_import(
    db: Session,
    call_import_id: UUID,
    organization_id: UUID,
    principal: Principal,
) -> CallImportDeleteResponse:
    call_import = (
        db.query(CallImport)
        .filter(
            CallImport.id == call_import_id,
            CallImport.organization_id == organization_id,
        )
        .first()
    )
    if not call_import:
        return CallImportDeleteResponse(
            id=call_import_id,
            status="completed",
        )

    if call_import.status == CallImportStatus.DELETING:
        return CallImportDeleteResponse(
            id=call_import.id,
            status="accepted",
        )

    call_import.status = CallImportStatus.DELETING
    call_import.error_message = None
    stamp_call_import_actor(call_import, principal)
    db.commit()

    from app.workers.tasks.call_import_bulk_ops import delete_call_import_task

    delete_call_import_task.delay(
        str(call_import_id),
        str(organization_id),
    )

    return CallImportDeleteResponse(
        id=call_import.id,
        status="accepted",
    )


def delete_call_import_row(
    db: Session,
    call_import_id: UUID,
    row_id: UUID,
    organization_id: UUID,
    principal: Principal,
) -> None:
    from app.services.storage.s3_service import s3_service

    call_import = get_call_import_for_org_or_404(db, call_import_id, organization_id)

    from app.db_sharding.row_ops import close_row_sessions

    row_db, row, extra_catalog = locate_call_import_row_or_404(
        db,
        call_import_id=call_import.id,
        row_id=row_id,
        organization_id=organization_id,
    )
    try:
        revoke_pending_tasks([row])

        if row.recording_s3_key and s3_service.is_enabled():
            try:
                s3_service.delete_file_by_key(row.recording_s3_key)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to delete S3 object {} for row {}: {}",
                    row.recording_s3_key,
                    row.id,
                    exc,
                )

        row_db.delete(row)
        row_db.commit()

        recompute_call_import_counters(db, call_import)
        stamp_call_import_actor(call_import, principal)
        db.commit()
    finally:
        close_row_sessions(row_db, extra_catalog)

    logger.info(
        "Deleted call_import_row {} (call_import={}, org={})",
        row_id,
        call_import.id,
        organization_id,
    )


def retry_failed_call_import_rows(
    db: Session,
    call_import_id: UUID,
    organization_id: UUID,
    principal: Principal,
    payload: Optional[CallImportRetryFailedRowsRequest] = None,
) -> CallImportRetryFailedRowsResponse:
    call_import = get_call_import_for_org_or_404(db, call_import_id, organization_id)

    if payload is not None:
        from app.services.call_imports.import_batch_helpers import (
            resolve_telephony_integration,
            validate_credentialed_import_ready,
            validate_telephony_credentials_live,
        )
        from app.services.call_imports.source_parse import _resolve_schema

        if payload.telephony_integration_id is not None:
            integration = resolve_telephony_integration(
                db,
                organization_id,
                payload.telephony_integration_id,
                payload.provider or "",
            )
            validate_telephony_credentials_live(db, organization_id, integration)
            call_import.provider = integration.provider
            call_import.telephony_integration_id = integration.id
            if (integration.provider or "").lower() in {"exotel", "plivo"}:
                schema = _resolve_schema(
                    db,
                    organization_id,
                    call_import.workspace_id,
                    call_import.schema_id,
                )
                validate_credentialed_import_ready(
                    integration.provider,
                    list(schema.parameters),
                    dict(call_import.parameter_mapping or {}),
                )
        else:
            call_import.provider = None
            call_import.telephony_integration_id = None
        stamp_call_import_actor(call_import, principal)
        db.commit()

    from app.services.call_imports.bulk_ops import (
        mark_import_rows_enqueue_failed,
        requeue_failed_import_rows,
    )
    from app.workers.concurrency.fair_import_dispatch import (
        schedule_fair_import_dispatch,
    )

    reset_ids = requeue_failed_import_rows(db, call_import.id)
    if not reset_ids:
        return CallImportRetryFailedRowsResponse(
            requeued=0,
            enqueue_failed=0,
            skipped=0,
        )

    recompute_call_import_counters(db, call_import)
    if payload is None:
        stamp_call_import_actor(call_import, principal)
    db.commit()

    try:
        schedule_fair_import_dispatch(max_workspace_turns=999)
        requeued = len(reset_ids)
        enqueue_failed = 0
        skipped = 0
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Failed to schedule fair import dispatch for import {}",
            call_import.id,
        )
        requeued = 0
        enqueue_failed, skipped = mark_import_rows_enqueue_failed(
            db,
            call_import.id,
            reset_ids,
            f"Failed to enqueue retry: {exc}",
        )
        recompute_call_import_counters(db, call_import)
        db.commit()

    return CallImportRetryFailedRowsResponse(
        requeued=requeued,
        enqueue_failed=enqueue_failed,
        skipped=skipped,
    )


def bulk_delete_call_import_rows(
    db: Session,
    call_import_id: UUID,
    organization_id: UUID,
    principal: Principal,
    payload: CallImportRowBulkDelete,
) -> CallImportRowBulkDeleteResponse:
    call_import = get_call_import_for_org_or_404(db, call_import_id, organization_id)

    if not payload.row_ids and payload.row_filter is None:
        return CallImportRowBulkDeleteResponse(deleted=0, status="completed")

    from app.workers.tasks.call_import_bulk_ops import bulk_delete_call_import_rows_task

    stamp_call_import_actor(call_import, principal)
    db.commit()

    bulk_delete_call_import_rows_task.delay(
        str(call_import_id),
        str(organization_id),
        [str(rid) for rid in payload.row_ids] if payload.row_ids else None,
        payload.row_filter.model_dump(mode="json") if payload.row_filter else None,
    )

    return CallImportRowBulkDeleteResponse(deleted=0, status="accepted")


def start_legacy_call_import(
    db: Session,
    call_import_id: UUID,
    organization_id: UUID,
    workspace_id: UUID,
    principal: Principal,
    payload: CallImportStartRequest,
) -> CallImportUploadResponse:
    from sqlalchemy.orm import selectinload as _selectinload

    call_import = (
        db.query(CallImport)
        .options(_selectinload(CallImport.tags))
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

    if call_import.status != CallImportStatus.MAPPED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot start import for a batch in status "
                f"'{call_import.status.value}'. Map the columns first."
            ),
        )

    if not call_import.source_s3_key or not call_import.source_format:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This batch has no staged source file and cannot be imported "
                "through the staged flow."
            ),
        )

    if not call_import.schema_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot start import without a mapped schema.",
        )

    schema = _resolve_schema(
        db, organization_id, workspace_id, call_import.schema_id
    )
    parameters = list(schema.parameters)

    if payload.telephony_integration_id is not None:
        integration = resolve_telephony_integration(
            db,
            organization_id,
            payload.telephony_integration_id,
            payload.provider or "",
        )
        validate_telephony_credentials_live(db, organization_id, integration)
        if (integration.provider or "").lower() in {"exotel", "plivo"}:
            validate_credentialed_import_ready(
                integration.provider,
                parameters,
                dict(call_import.parameter_mapping or {}),
            )
    else:
        validate_direct_url_import_ready(
            parameters, dict(call_import.parameter_mapping or {})
        )
        integration = None

    ensure_blob_storage_enabled()

    if integration is not None:
        call_import.provider = integration.provider
        call_import.telephony_integration_id = integration.id
    else:
        call_import.provider = None
        call_import.telephony_integration_id = None

    call_import.total_rows = 0
    call_import.completed_rows = 0
    call_import.failed_rows = 0
    call_import.error_message = None
    call_import.status = CallImportStatus.PROCESSING
    stamp_call_import_actor(call_import, principal)
    db.commit()
    db.refresh(call_import)

    from app.workers.tasks.call_import_bulk_ops import (
        materialize_call_import_rows_task,
    )

    materialize_call_import_rows_task.delay(
        str(call_import_id),
        str(organization_id),
        str(workspace_id),
        schedule_import_dispatch=True,
    )

    return CallImportUploadResponse(
        id=call_import.id,
        total_rows=0,
        status=call_import.status,
        dataset=call_import.dataset,
        tags=_tag_response_payload(call_import.tags),
        message=(
            "Import accepted. Rows are being materialized in the background; "
            "recordings will be fetched asynchronously."
        ),
    )
