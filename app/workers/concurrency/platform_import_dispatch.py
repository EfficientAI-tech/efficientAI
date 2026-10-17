"""Dispatch a single platform import row to the hydration worker."""

from __future__ import annotations

from uuid import UUID

from celery.utils import uuid as celery_uuid
from loguru import logger
from sqlalchemy import text
from sqlalchemy.orm import Session, load_only

from app.models.database import CallImport, CallImportRow
from app.models.enums import CallImportRowStatus, CallImportStatus
from app.workers.concurrency.fair_platform_import_dispatch import PLATFORM_IMPORTS_QUEUE
from app.workers.concurrency.platform_import_limits import (
    acquire_platform_lease,
    hydrate_enqueue_blocked,
    lease_is_active,
    mark_platform_task_published,
    platform_task_was_published,
    release_platform_lease,
)


def clear_expired_platform_row_claims(
    db: Session,
    *,
    platform_import_ids: set | None = None,
) -> int:
    """Drop task ids whose lease expired and that were never queued.

    A live lease is left alone. A task that reached the broker keeps its id
    until Celery says it has finished, so a deep queue is not fetched again.
    """
    claim_columns = load_only(
        CallImportRow.id,
        CallImportRow.celery_task_id,
        CallImportRow.status,
    )
    query = db.query(CallImportRow).options(claim_columns).filter(
        CallImportRow.celery_task_id.isnot(None),
        CallImportRow.status == CallImportRowStatus.PENDING,
    )
    if platform_import_ids is not None:
        if not platform_import_ids:
            return 0
        query = query.filter(CallImportRow.call_import_id.in_(platform_import_ids))
    stuck = db.query(CallImportRow).options(claim_columns).filter(
        CallImportRow.celery_task_id.isnot(None),
        CallImportRow.status == CallImportRowStatus.PROCESSING,
        CallImportRow.recording_s3_key.is_(None),
    )
    if platform_import_ids:
        stuck = stuck.filter(CallImportRow.call_import_id.in_(platform_import_ids))
    rows = query.limit(128).all() + stuck.limit(128).all()
    cleared = 0
    seen: set = set()
    for row in rows:
        if row.id in seen:
            continue
        seen.add(row.id)
        task_id = (row.celery_task_id or "").strip()
        if not task_id or lease_is_active(task_id):
            continue
        from app.workers.concurrency.dispatch_reconcile import (
            _celery_task_is_finished,
        )

        if not _celery_task_is_finished(task_id):
            published = platform_task_was_published(task_id)
            if published is None or published:
                continue
        row.celery_task_id = None
        if row.status == CallImportRowStatus.PROCESSING:
            row.status = CallImportRowStatus.PENDING
        cleared += 1
    if cleared:
        db.commit()
        logger.info("cleared expired platform row claims count={}", cleared)
    return cleared


def claim_next_platform_row_id(db: Session, call_import_id: UUID, task_id: str) -> UUID | None:
    """Claim one pending row and stamp the task id in the same statement."""
    row = db.execute(
        text(
            """
            UPDATE call_import_rows
            SET celery_task_id = :task_id,
                dispatched_at = now(),
                updated_at = now()
            WHERE id = (
                SELECT id FROM call_import_rows
                WHERE call_import_id = :call_import_id
                  AND status = 'pending'
                  AND celery_task_id IS NULL
                ORDER BY created_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING id
            """
        ),
        {"task_id": task_id, "call_import_id": call_import_id},
    ).first()
    if row is None:
        return None
    return row[0]


def try_dispatch_platform_import_row(
    *,
    db: Session,
    call_import: CallImport,
) -> bool:
    """Lease, claim, then publish. A failed publish gives the row back."""
    from app.workers.tasks.process_call_import_row import process_call_import_row_task

    if call_import.status == CallImportStatus.DELETING or call_import.paused_at:
        return False
    if hydrate_enqueue_blocked():
        return False

    reserved_task_id = celery_uuid()
    if not acquire_platform_lease(
        workspace_id=call_import.workspace_id,
        organization_id=call_import.organization_id,
        call_import_id=call_import.id,
        celery_task_id=reserved_task_id,
    ):
        return False

    try:
        claimed = claim_next_platform_row_id(db, call_import.id, reserved_task_id)
        if claimed is None:
            release_platform_lease(reserved_task_id)
            return False
        db.commit()
    except Exception:
        db.rollback()
        release_platform_lease(reserved_task_id)
        raise

    try:
        process_call_import_row_task.apply_async(
            args=(str(claimed),),
            kwargs={
                "_eval_slot_task_id": reserved_task_id,
                "_platform_import": True,
            },
            queue=PLATFORM_IMPORTS_QUEUE,
            task_id=reserved_task_id,
        )
        mark_platform_task_published(reserved_task_id)
    except Exception:
        db.execute(
            text(
                """
                UPDATE call_import_rows
                SET celery_task_id = NULL, updated_at = now()
                WHERE id = :row_id AND celery_task_id = :task_id
                """
            ),
            {"row_id": claimed, "task_id": reserved_task_id},
        )
        db.commit()
        release_platform_lease(reserved_task_id)
        raise
    return True
