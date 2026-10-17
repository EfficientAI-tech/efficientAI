"""Best-effort cleanup of orphaned dispatch locks after worker restarts."""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from loguru import logger
from sqlalchemy import func, or_, update
from sqlalchemy.orm import Session

from app.models.database import CallImportEvaluationRow, CallImportRow
from app.models.enums import CallImportRowStatus

if TYPE_CHECKING:
    from app.db_sharding.session_cache import ShardSessionCache

_RECONCILE_BATCH = 500


def claim_import_row_for_task(db: Session, row: CallImportRow, task_id: str | None) -> bool:
    """Take a recording row for this task. A second task must not download it.

    A pending row can be taken once, even if a task id was left on it. After
    the status is processing, only that same task id may continue.
    """
    cleaned = (task_id or "").strip()
    filters = [
        CallImportRow.id == row.id,
        CallImportRow.status.in_(
            (CallImportRowStatus.PENDING, CallImportRowStatus.PROCESSING)
        ),
    ]
    if cleaned:
        filters.append(
            or_(
                CallImportRow.status == CallImportRowStatus.PENDING,
                CallImportRow.celery_task_id == cleaned,
            )
        )
    else:
        filters.append(CallImportRow.status == CallImportRowStatus.PENDING)
    values: dict = {
        "status": CallImportRowStatus.PROCESSING,
        "error_message": None,
        "attempts": func.coalesce(CallImportRow.attempts, 0) + 1,
    }
    if cleaned:
        values["celery_task_id"] = cleaned
    result = db.execute(update(CallImportRow).where(*filters).values(**values))
    if result.rowcount != 1:
        db.rollback()
        return False
    db.commit()
    db.refresh(row)
    return True


def _reconcile_import_rows_on_session(db: Session) -> int:
    cleared = 0
    rows = (
        db.query(CallImportRow)
        .filter(
            CallImportRow.celery_task_id.isnot(None),
            CallImportRow.status.in_(
                (CallImportRowStatus.PENDING, CallImportRowStatus.PROCESSING)
            ),
        )
        .limit(_RECONCILE_BATCH)
        .all()
    )
    for row in rows:
        task_id = (row.celery_task_id or "").strip()
        if not task_id or not _celery_task_is_finished(task_id):
            continue
        row.celery_task_id = None
        if (
            row.status == CallImportRowStatus.PROCESSING
            and not (row.recording_s3_key or "").strip()
        ):
            row.status = CallImportRowStatus.PENDING
        cleared += 1
    if cleared:
        db.commit()
    return cleared


def reconcile_orphaned_import_dispatch_locks(catalog_db: Session) -> int:
    """Clear stale import-row task ids so fair import dispatch can resume."""
    from app.db_sharding.sessions import is_sharding_enabled

    if not is_sharding_enabled():
        return _reconcile_import_rows_on_session(catalog_db)

    from app.db_sharding.pool_manager import db_pool_manager

    router = db_pool_manager.router
    assert router is not None
    total = 0
    for shard_id in router.shard_ids:
        shard_db = db_pool_manager.shard_session_factory(shard_id)()
        try:
            total += _reconcile_import_rows_on_session(shard_db)
        finally:
            shard_db.close()
    return total


def _celery_task_is_finished(task_id: str) -> bool:
    """True only when Celery has finished this task.

    ``PENDING`` is a task waiting in the broker. It must not be treated as
    dead, or the row is dispatched to the model again.
    """
    cleaned = (task_id or "").strip()
    if not cleaned:
        return False
    try:
        from app.workers.celery_app import celery_app

        state = celery_app.AsyncResult(cleaned).state
    except Exception as exc:
        logger.debug("Celery state lookup failed for {}: {}", task_id, exc)
        return False
    return state in {"SUCCESS", "FAILURE", "REVOKED"}


def _reconcile_eval_rows_on_session(db: Session) -> int:
    cleared = 0
    rows = (
        db.query(CallImportEvaluationRow)
        .filter(
            CallImportEvaluationRow.celery_task_id.isnot(None),
            CallImportEvaluationRow.status == "pending",
        )
        .limit(_RECONCILE_BATCH)
        .all()
    )
    for row in rows:
        task_id = (row.celery_task_id or "").strip()
        if not task_id or not _celery_task_is_finished(task_id):
            continue
        row.celery_task_id = None
        cleared += 1
    if cleared:
        db.commit()
    return cleared


def reconcile_orphaned_eval_dispatch_locks(
    catalog_db: Session,
    *,
    shard_cache: Optional["ShardSessionCache"] = None,
) -> int:
    """Clear stale eval-row task ids so fair eval dispatch can resume."""
    from app.db_sharding.sessions import is_sharding_enabled

    if not is_sharding_enabled():
        return _reconcile_eval_rows_on_session(catalog_db)

    from app.db_sharding.pool_manager import db_pool_manager

    router = db_pool_manager.router
    assert router is not None
    total = 0
    for shard_id in router.shard_ids:
        if shard_cache is not None:
            shard_db = shard_cache.session_for(shard_id)
            owns_session = False
        else:
            shard_db = db_pool_manager.shard_session_factory(shard_id)()
            owns_session = True
        try:
            total += _reconcile_eval_rows_on_session(shard_db)
        finally:
            if owns_session:
                shard_db.close()
    return total
