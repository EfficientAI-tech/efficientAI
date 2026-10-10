"""Dispatch single platform import row to hydration worker."""

from __future__ import annotations

from celery.utils import uuid as celery_uuid
from sqlalchemy.orm import Session

from app.models.database import CallImport, CallImportRow
from app.models.enums import CallImportRowStatus, CallImportStatus
from app.workers.concurrency.fair_platform_import_dispatch import PLATFORM_IMPORTS_QUEUE
from app.workers.concurrency.platform_import_limits import acquire_platform_import_slot


def try_dispatch_platform_import_row(
    *,
    db: Session,
    row: CallImportRow,
    call_import: CallImport,
) -> bool:
    from app.workers.tasks.process_call_import_row import process_call_import_row_task

    if row.status != CallImportRowStatus.PENDING or row.celery_task_id:
        return False
    if call_import.status == CallImportStatus.DELETING or call_import.paused_at:
        return False

    reserved_task_id = celery_uuid()
    if not acquire_platform_import_slot(
        workspace_id=call_import.workspace_id,
        organization_id=call_import.organization_id,
        celery_task_id=reserved_task_id,
    ):
        return False

    try:
        async_result = process_call_import_row_task.apply_async(
            args=(str(row.id),),
            kwargs={"_eval_slot_task_id": reserved_task_id, "_platform_import": True},
            queue=PLATFORM_IMPORTS_QUEUE,
            task_id=reserved_task_id,
        )
    except Exception:
        from app.workers.concurrency.platform_import_limits import (
            release_platform_import_slot,
        )

        release_platform_import_slot(reserved_task_id)
        raise

    row.celery_task_id = async_result.id
    db.commit()
    return True
