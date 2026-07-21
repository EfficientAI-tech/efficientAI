"""Best-effort cleanup of orphaned dispatch locks after worker restarts."""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from loguru import logger
from sqlalchemy.orm import Session

from app.models.database import CallImportEvaluationRow, CallImportRow
from app.models.enums import CallImportRowStatus

if TYPE_CHECKING:
    from app.db_sharding.session_cache import ShardSessionCache

_RECONCILE_BATCH = 500


def _celery_task_is_active(task_id: str) -> bool:
    """Return True when a Celery task id is still queued or running."""
    cleaned = (task_id or "").strip()
    if not cleaned:
        return False
    try:
        from app.workers.celery_app import celery_app

        result = celery_app.AsyncResult(cleaned)
        state = result.state
        if state in {"STARTED", "RETRY"}:
            return True
        if state in {"SUCCESS", "FAILURE", "REVOKED"}:
            return False

        inspect = celery_app.control.inspect(timeout=0.5)
        if inspect is None:
            return False
        for method_name in ("active", "reserved", "scheduled"):
            method = getattr(inspect, method_name, None)
            if method is None:
                continue
            payload = method() or {}
            for tasks in payload.values():
                for task in tasks:
                    if task.get("id") == cleaned:
                        return True
        return False
    except Exception as exc:
        logger.debug("Celery task inspect failed for {}: {}", task_id, exc)
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
        if not task_id or _celery_task_is_active(task_id):
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
        if not task_id or _celery_task_is_active(task_id):
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
