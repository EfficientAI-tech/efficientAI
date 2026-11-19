"""Chunked, resumable teardown for whole call-import batches."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Tuple
from uuid import UUID

from loguru import logger
from sqlalchemy import delete, func
from sqlalchemy.orm import Session

from app.models.database import (
    CallImport,
    CallImportDiscoverySlice,
    CallImportEvaluation,
    CallImportEvaluationExport,
    CallImportEvaluationPdfReport,
    CallImportEvaluationReportSnapshot,
    CallImportEvaluationRow,
    CallImportRow,
    CallImportShardSlice,
    CallImportTagAssignment,
    PlatformConversationLedger,
)
from app.models.enums import CallImportStatus
from app.services.call_imports.delete_teardown_lock import (
    clear_call_import_delete_lock,
    ensure_call_import_delete_lock,
)

TEARDOWN_PAGE_SIZE = 500
_REVOKE_TASK_BATCH = 500
_FAILED_DELETE_PREFIX = "Failed to delete import:"


def _catalog_row_sessions(catalog_db: Session) -> List[Tuple[Session, bool]]:
    """(session, must_close) for catalog first, then each row shard."""
    from app.db_sharding.pool_manager import db_pool_manager
    from app.db_sharding.sessions import is_sharding_enabled

    out: List[Tuple[Session, bool]] = []
    if not is_sharding_enabled():
        out.append((catalog_db, False))
        return out
    out.append((catalog_db, False))
    router = db_pool_manager.router
    if router is None:
        return out
    for shard_id in router.shard_ids:
        factory = db_pool_manager.shard_session_factory(shard_id)
        out.append((factory(), True))
    return out


def _close_extra_sessions(sessions: List[Tuple[Session, bool]]) -> None:
    for session, must_close in sessions:
        if must_close:
            session.close()


def import_delete_resumable(call_import: CallImport) -> bool:
    if call_import.status == CallImportStatus.DELETING:
        return True
    if call_import.status == CallImportStatus.FAILED:
        msg = (call_import.error_message or "").strip()
        return msg.startswith(_FAILED_DELETE_PREFIX)
    return False


def _touch_import_deleting(catalog_db: Session, call_import: CallImport) -> None:
    if call_import.status != CallImportStatus.DELETING:
        call_import.status = CallImportStatus.DELETING
    call_import.updated_at = datetime.now(timezone.utc)
    catalog_db.commit()


def _import_rows_remain(catalog_db: Session, call_import_id: UUID) -> bool:
    sessions = _catalog_row_sessions(catalog_db)
    try:
        for session, _must_close in sessions:
            count = (
                session.query(func.count(CallImportRow.id))
                .filter(CallImportRow.call_import_id == call_import_id)
                .scalar()
            )
            if int(count or 0) > 0:
                return True
    finally:
        _close_extra_sessions(sessions)
    return False


def _catalog_children_remain(catalog_db: Session, call_import_id: UUID) -> bool:
    checks = [
        catalog_db.query(func.count(PlatformConversationLedger.id)).filter(
            PlatformConversationLedger.call_import_id == call_import_id
        ),
        catalog_db.query(func.count(CallImportEvaluation.id)).filter(
            CallImportEvaluation.call_import_id == call_import_id
        ),
        catalog_db.query(func.count(CallImportEvaluationReportSnapshot.id)).filter(
            CallImportEvaluationReportSnapshot.call_import_id == call_import_id
        ),
        catalog_db.query(func.count(CallImportEvaluationPdfReport.id)).filter(
            CallImportEvaluationPdfReport.call_import_id == call_import_id
        ),
        catalog_db.query(func.count(CallImportEvaluationExport.id)).filter(
            CallImportEvaluationExport.call_import_id == call_import_id
        ),
        catalog_db.query(func.count(CallImportDiscoverySlice.call_import_id)).filter(
            CallImportDiscoverySlice.call_import_id == call_import_id
        ),
        catalog_db.query(func.count(CallImportShardSlice.call_import_id)).filter(
            CallImportShardSlice.call_import_id == call_import_id
        ),
        catalog_db.query(func.count(CallImportTagAssignment.call_import_id)).filter(
            CallImportTagAssignment.call_import_id == call_import_id
        ),
    ]
    for query in checks:
        if int(query.scalar() or 0) > 0:
            return True
    return False


def _revoke_task_ids(task_ids: List[str]) -> None:
    if not task_ids:
        return
    try:
        from app.workers.celery_app import celery_app

        for start in range(0, len(task_ids), _REVOKE_TASK_BATCH):
            celery_app.control.revoke(task_ids[start : start + _REVOKE_TASK_BATCH], terminate=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to revoke tasks during import teardown: {}", exc)


def _delete_one_page_import_rows(
    session: Session,
    call_import_id: UUID,
) -> int:
    row_ids = [
        row_id
        for (row_id,) in (
            session.query(CallImportRow.id)
            .filter(CallImportRow.call_import_id == call_import_id)
            .order_by(CallImportRow.id.asc())
            .limit(TEARDOWN_PAGE_SIZE)
            .all()
        )
    ]
    if not row_ids:
        return 0

    task_ids = [
        tid
        for (tid,) in (
            session.query(CallImportRow.celery_task_id)
            .filter(CallImportRow.id.in_(row_ids))
            .all()
        )
        if tid
    ]
    _revoke_task_ids([str(t) for t in task_ids])

    session.query(CallImportEvaluationRow).filter(
        CallImportEvaluationRow.call_import_row_id.in_(row_ids)
    ).delete(synchronize_session=False)
    deleted = (
        session.query(CallImportRow)
        .filter(
            CallImportRow.call_import_id == call_import_id,
            CallImportRow.id.in_(row_ids),
        )
        .delete(synchronize_session=False)
    )
    session.commit()
    return int(deleted or 0)


def _delete_one_page_catalog_children(catalog_db: Session, call_import_id: UUID) -> int:
    """Delete one page of catalog-attached artefacts (not import rows)."""
    total = 0

    ledger_ids = [
        lid
        for (lid,) in (
            catalog_db.query(PlatformConversationLedger.id)
            .filter(PlatformConversationLedger.call_import_id == call_import_id)
            .order_by(PlatformConversationLedger.id.asc())
            .limit(TEARDOWN_PAGE_SIZE)
            .all()
        )
    ]
    if ledger_ids:
        total += (
            catalog_db.query(PlatformConversationLedger)
            .filter(PlatformConversationLedger.id.in_(ledger_ids))
            .delete(synchronize_session=False)
            or 0
        )
        catalog_db.commit()
        return int(total)

    snapshot_ids = [
        sid
        for (sid,) in (
            catalog_db.query(CallImportEvaluationReportSnapshot.id)
            .filter(CallImportEvaluationReportSnapshot.call_import_id == call_import_id)
            .order_by(CallImportEvaluationReportSnapshot.id.asc())
            .limit(TEARDOWN_PAGE_SIZE)
            .all()
        )
    ]
    if snapshot_ids:
        catalog_db.query(CallImportEvaluationPdfReport).filter(
            CallImportEvaluationPdfReport.snapshot_id.in_(snapshot_ids)
        ).delete(synchronize_session=False)
        total += (
            catalog_db.query(CallImportEvaluationReportSnapshot)
            .filter(CallImportEvaluationReportSnapshot.id.in_(snapshot_ids))
            .delete(synchronize_session=False)
            or 0
        )
        catalog_db.commit()
        return int(total)

    pdf_ids = [
        pid
        for (pid,) in (
            catalog_db.query(CallImportEvaluationPdfReport.id)
            .filter(CallImportEvaluationPdfReport.call_import_id == call_import_id)
            .order_by(CallImportEvaluationPdfReport.id.asc())
            .limit(TEARDOWN_PAGE_SIZE)
            .all()
        )
    ]
    if pdf_ids:
        total += (
            catalog_db.query(CallImportEvaluationPdfReport)
            .filter(CallImportEvaluationPdfReport.id.in_(pdf_ids))
            .delete(synchronize_session=False)
            or 0
        )
        catalog_db.commit()
        return int(total)

    export_ids = [
        eid
        for (eid,) in (
            catalog_db.query(CallImportEvaluationExport.id)
            .filter(CallImportEvaluationExport.call_import_id == call_import_id)
            .order_by(CallImportEvaluationExport.id.asc())
            .limit(TEARDOWN_PAGE_SIZE)
            .all()
        )
    ]
    if export_ids:
        total += (
            catalog_db.query(CallImportEvaluationExport)
            .filter(CallImportEvaluationExport.id.in_(export_ids))
            .delete(synchronize_session=False)
            or 0
        )
        catalog_db.commit()
        return int(total)

    eval_ids = [
        eid
        for (eid,) in (
            catalog_db.query(CallImportEvaluation.id)
            .filter(CallImportEvaluation.call_import_id == call_import_id)
            .order_by(CallImportEvaluation.id.asc())
            .limit(TEARDOWN_PAGE_SIZE)
            .all()
        )
    ]
    if eval_ids:
        from app.services.call_imports.eval_progress_buffer import (
            delete as delete_eval_counters,
        )

        for eval_id in eval_ids:
            delete_eval_counters(eval_id)
        total += (
            catalog_db.query(CallImportEvaluation)
            .filter(CallImportEvaluation.id.in_(eval_ids))
            .delete(synchronize_session=False)
            or 0
        )
        catalog_db.commit()
        return int(total)

    slice_rows = (
        catalog_db.query(CallImportDiscoverySlice)
        .filter(CallImportDiscoverySlice.call_import_id == call_import_id)
        .limit(TEARDOWN_PAGE_SIZE)
        .all()
    )
    if slice_rows:
        for row in slice_rows:
            catalog_db.delete(row)
        catalog_db.commit()
        return len(slice_rows)

    shard_slices = (
        catalog_db.query(CallImportShardSlice)
        .filter(CallImportShardSlice.call_import_id == call_import_id)
        .limit(TEARDOWN_PAGE_SIZE)
        .all()
    )
    if shard_slices:
        for row in shard_slices:
            catalog_db.delete(row)
        catalog_db.commit()
        return len(shard_slices)

    tag_rows = (
        catalog_db.query(CallImportTagAssignment)
        .filter(CallImportTagAssignment.call_import_id == call_import_id)
        .limit(TEARDOWN_PAGE_SIZE)
        .all()
    )
    if tag_rows:
        for row in tag_rows:
            catalog_db.delete(row)
        catalog_db.commit()
        return len(tag_rows)

    return 0


def _platform_release_key(call_import_id: UUID) -> str:
    return f"call_import:delete:{call_import_id}:platform_released"


def _release_platform_once(catalog_db: Session, call_import: CallImport) -> None:
    from app.config import settings
    import redis as redis_lib

    key = _platform_release_key(call_import.id)
    try:
        client = redis_lib.from_url(settings.REDIS_URL, decode_responses=True)
        if not client.set(key, "1", nx=True, ex=7200):
            return
    except redis_lib.RedisError:
        pass

    from app.services.call_imports.bulk_ops import _release_platform_import_work

    _release_platform_import_work(catalog_db, call_import)


def _sweep_s3_prefix(organization_id: UUID, call_import_id: UUID) -> tuple[int, int]:
    from app.services.storage.s3_service import s3_service

    if not s3_service.is_enabled():
        return 0, 0
    sweep_prefix = (
        f"{s3_service.prefix}organizations/{organization_id}/"
        f"call_imports/{call_import_id}/"
    )
    try:
        deleted_objects, errs = s3_service.delete_keys_by_prefix(sweep_prefix)
        return int(deleted_objects or 0), len(errs or [])
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "S3 prefix sweep failed for call_import {}: {}",
            call_import_id,
            exc,
        )
        return 0, 0


def _schedule_delete_continuation(call_import_id: UUID, organization_id: UUID) -> None:
    from app.workers.tasks.call_import_bulk_ops import delete_call_import_task

    delete_call_import_task.delay(str(call_import_id), str(organization_id))


def execute_call_import_delete_chunk(
    catalog_db: Session,
    call_import_id: UUID,
    organization_id: UUID,
) -> dict:
    """One bounded chunk of import teardown. Re-enqueues itself when work remains."""
    if not ensure_call_import_delete_lock(call_import_id):
        logger.info(
            "execute_call_import_delete_chunk: lock busy for import {}",
            call_import_id,
        )
        return {"status": "skipped", "reason": "lock_busy"}

    call_import = (
        catalog_db.query(CallImport)
        .filter(
            CallImport.id == call_import_id,
            CallImport.organization_id == organization_id,
        )
        .first()
    )
    if call_import is None:
        clear_call_import_delete_lock(call_import_id)
        return {"status": "completed", "deleted_rows": 0}

    if not import_delete_resumable(call_import):
        clear_call_import_delete_lock(call_import_id)
        return {"status": "skipped", "reason": "not_deleting"}

    total_rows_before = int(call_import.total_rows or 0)

    try:
        _release_platform_once(catalog_db, call_import)

        progress = 0
        row_sessions = _catalog_row_sessions(catalog_db)
        try:
            for session, _must_close in row_sessions:
                deleted = _delete_one_page_import_rows(session, call_import_id)
                if deleted:
                    progress = deleted
                    break
        finally:
            _close_extra_sessions(row_sessions)

        if progress:
            _touch_import_deleting(catalog_db, call_import)
            ensure_call_import_delete_lock(call_import_id)
            _schedule_delete_continuation(call_import_id, organization_id)
            return {
                "status": "continuing",
                "deleted_rows": progress,
            }

        if _import_rows_remain(catalog_db, call_import_id):
            _touch_import_deleting(catalog_db, call_import)
            ensure_call_import_delete_lock(call_import_id)
            _schedule_delete_continuation(call_import_id, organization_id)
            return {"status": "continuing", "deleted_rows": 0}

        child_deleted = _delete_one_page_catalog_children(catalog_db, call_import_id)
        if child_deleted or _catalog_children_remain(catalog_db, call_import_id):
            _touch_import_deleting(catalog_db, call_import)
            ensure_call_import_delete_lock(call_import_id)
            _schedule_delete_continuation(call_import_id, organization_id)
            return {
                "status": "continuing",
                "deleted_catalog_children": child_deleted,
            }

        catalog_db.execute(
            delete(CallImport).where(
                CallImport.id == call_import_id,
                CallImport.organization_id == organization_id,
            )
        )
        catalog_db.commit()

        s3_deleted, s3_errors = _sweep_s3_prefix(organization_id, call_import_id)
        clear_call_import_delete_lock(call_import_id)
        try:
            import redis as redis_lib
            from app.config import settings

            redis_lib.from_url(settings.REDIS_URL, decode_responses=True).delete(
                _platform_release_key(call_import_id)
            )
        except Exception:  # noqa: BLE001
            pass

        logger.info(
            "Deleted call_import {} (org={}, rows={}, s3_objects_deleted={}, s3_errors={})",
            call_import_id,
            organization_id,
            total_rows_before,
            s3_deleted,
            s3_errors,
        )
        return {
            "status": "completed",
            "deleted_rows": total_rows_before,
            "s3_objects_deleted": s3_deleted,
            "s3_errors": s3_errors,
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Chunk failed during call_import delete {}",
            call_import_id,
        )
        catalog_db.rollback()
        call_import = (
            catalog_db.query(CallImport)
            .filter(
                CallImport.id == call_import_id,
                CallImport.organization_id == organization_id,
            )
            .first()
        )
        if call_import is not None:
            call_import.status = CallImportStatus.DELETING
            call_import.error_message = f"{_FAILED_DELETE_PREFIX} {exc}"
            call_import.updated_at = datetime.now(timezone.utc)
            catalog_db.commit()
        clear_call_import_delete_lock(call_import_id)
        return {"status": "error", "error": str(exc)}