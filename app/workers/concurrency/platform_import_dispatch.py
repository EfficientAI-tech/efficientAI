"""Dispatch single platform import row to hydration worker."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from celery.utils import uuid as celery_uuid
from loguru import logger
from sqlalchemy.orm import Session

from app.config import settings
from app.models.database import CallImport, CallImportRow
from app.models.enums import CallImportRowStatus, CallImportStatus
from app.workers.concurrency.fair_platform_import_dispatch import PLATFORM_IMPORTS_QUEUE
from app.workers.concurrency.platform_import_limits import (
    acquire_platform_import_slot,
    release_platform_import_slot,
)


def reclaim_stale_platform_import_dispatches(db: Session) -> int:
    """Release slots and clear task ids for rows stuck queued before first attempt."""
    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=settings.PLATFORM_IMPORT_STALE_DISPATCH_SECONDS
    )
    rows = (
        db.query(CallImportRow)
        .join(CallImport, CallImport.id == CallImportRow.call_import_id)
        .filter(
            CallImport.source_format == "platform",
            CallImport.status != CallImportStatus.DELETING,
            CallImportRow.status == CallImportRowStatus.PENDING,
            CallImportRow.celery_task_id.isnot(None),
            CallImportRow.attempts == 0,
            CallImportRow.updated_at < cutoff,
        )
        .limit(512)
        .all()
    )
    if not rows:
        return 0
    reclaimed = 0
    for row in rows:
        task_id = (row.celery_task_id or "").strip()
        if not task_id:
            continue
        row.celery_task_id = None
        release_platform_import_slot(task_id)
        reclaimed += 1
    if reclaimed:
        db.commit()
        logger.info("reclaimed stale platform import dispatches count={}", reclaimed)
    return reclaimed


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
            priority=8,
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
