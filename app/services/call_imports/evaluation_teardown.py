"""Chunked, resumable teardown for call-import evaluation runs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Tuple
from uuid import UUID

from loguru import logger
from sqlalchemy import delete, func
from sqlalchemy.orm import Session

from app.models.database import (
    CallImportEvaluation,
    CallImportEvaluationExport,
    CallImportEvaluationPdfReport,
    CallImportEvaluationReportSnapshot,
    CallImportEvaluationRow,
    EvaluationAnalysisBatch,
)
from app.services.call_imports.delete_teardown_lock import (
    clear_eval_delete_lock,
    refresh_eval_delete_lock,
    try_acquire_eval_delete_lock,
)

TEARDOWN_PAGE_SIZE = 500
_REVOKE_TASK_BATCH = 500
EVAL_DELETING_STATUS = "deleting"


def _catalog_and_shard_sessions(catalog_db: Session) -> List[Tuple[Session, bool]]:
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


def _revoke_task_ids(task_ids: List[str]) -> None:
    if not task_ids:
        return
    try:
        from app.workers.celery_app import celery_app

        for start in range(0, len(task_ids), _REVOKE_TASK_BATCH):
            celery_app.control.revoke(task_ids[start : start + _REVOKE_TASK_BATCH], terminate=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to revoke tasks during eval teardown: {}", exc)


def _delete_one_page_eval_rows(session: Session, evaluation_id: UUID) -> int:
    rows = (
        session.query(CallImportEvaluationRow)
        .filter(CallImportEvaluationRow.evaluation_id == evaluation_id)
        .order_by(CallImportEvaluationRow.id.asc())
        .limit(TEARDOWN_PAGE_SIZE)
        .all()
    )
    if not rows:
        return 0

    task_ids = [
        r.celery_task_id
        for r in rows
        if r.celery_task_id and (r.status or "") in {"pending", "running"}
    ]
    _revoke_task_ids([str(t) for t in task_ids if t])

    row_ids = [r.id for r in rows]
    deleted = (
        session.query(CallImportEvaluationRow)
        .filter(CallImportEvaluationRow.id.in_(row_ids))
        .delete(synchronize_session=False)
    )
    session.commit()
    return int(deleted or 0)


def _eval_rows_remain(catalog_db: Session, evaluation_id: UUID) -> bool:
    sessions = _catalog_and_shard_sessions(catalog_db)
    try:
        for session, _ in sessions:
            count = (
                session.query(func.count(CallImportEvaluationRow.id))
                .filter(CallImportEvaluationRow.evaluation_id == evaluation_id)
                .scalar()
            )
            if int(count or 0) > 0:
                return True
    finally:
        _close_extra_sessions(sessions)
    return False


def _delete_catalog_artifacts_for_eval(catalog_db: Session, evaluation_id: UUID) -> int:
    total = 0
    snapshot_ids = [
        sid
        for (sid,) in (
            catalog_db.query(CallImportEvaluationReportSnapshot.id)
            .filter(CallImportEvaluationReportSnapshot.evaluation_id == evaluation_id)
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

    pdf_ids = [
        pid
        for (pid,) in (
            catalog_db.query(CallImportEvaluationPdfReport.id)
            .filter(CallImportEvaluationPdfReport.evaluation_id == evaluation_id)
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

    export_ids = [
        eid
        for (eid,) in (
            catalog_db.query(CallImportEvaluationExport.id)
            .filter(CallImportEvaluationExport.evaluation_id == evaluation_id)
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

    batch_ids = [
        bid
        for (bid,) in (
            catalog_db.query(EvaluationAnalysisBatch.id)
            .filter(EvaluationAnalysisBatch.evaluation_id == evaluation_id)
            .limit(TEARDOWN_PAGE_SIZE)
            .all()
        )
    ]
    if batch_ids:
        total += (
            catalog_db.query(EvaluationAnalysisBatch)
            .filter(EvaluationAnalysisBatch.id.in_(batch_ids))
            .delete(synchronize_session=False)
            or 0
        )

    if total:
        catalog_db.commit()
    return int(total)


def _artifacts_remain(catalog_db: Session, evaluation_id: UUID) -> bool:
    if (
        catalog_db.query(func.count(CallImportEvaluationReportSnapshot.id))
        .filter(CallImportEvaluationReportSnapshot.evaluation_id == evaluation_id)
        .scalar()
    ):
        return True
    if (
        catalog_db.query(func.count(CallImportEvaluationPdfReport.id))
        .filter(CallImportEvaluationPdfReport.evaluation_id == evaluation_id)
        .scalar()
    ):
        return True
    if (
        catalog_db.query(func.count(CallImportEvaluationExport.id))
        .filter(CallImportEvaluationExport.evaluation_id == evaluation_id)
        .scalar()
    ):
        return True
    if (
        catalog_db.query(func.count(EvaluationAnalysisBatch.id))
        .filter(EvaluationAnalysisBatch.evaluation_id == evaluation_id)
        .scalar()
    ):
        return True
    return False


def _schedule_eval_delete_continuation(
    evaluation_id: UUID,
    organization_id: UUID,
    call_import_id: UUID,
) -> None:
    from app.workers.tasks.call_import_bulk_ops import delete_call_import_evaluation_task

    delete_call_import_evaluation_task.delay(
        str(evaluation_id),
        str(organization_id),
        str(call_import_id),
    )


def _claim_eval_delete_lock(evaluation_id: UUID) -> bool:
    if refresh_eval_delete_lock(evaluation_id):
        return True
    return try_acquire_eval_delete_lock(evaluation_id)


def execute_evaluation_delete_chunk(
    catalog_db: Session,
    evaluation_id: UUID,
    organization_id: UUID,
    call_import_id: UUID,
) -> dict:
    if not _claim_eval_delete_lock(evaluation_id):
        return {"status": "skipped", "reason": "lock_busy"}

    evaluation = (
        catalog_db.query(CallImportEvaluation)
        .filter(
            CallImportEvaluation.id == evaluation_id,
            CallImportEvaluation.organization_id == organization_id,
            CallImportEvaluation.call_import_id == call_import_id,
        )
        .first()
    )
    if evaluation is None:
        clear_eval_delete_lock(evaluation_id)
        from app.services.call_imports.eval_progress_buffer import (
            delete as delete_eval_counters,
        )

        delete_eval_counters(evaluation_id)
        return {"status": "completed"}

    if (evaluation.status or "").strip().lower() != EVAL_DELETING_STATUS:
        clear_eval_delete_lock(evaluation_id)
        return {"status": "skipped", "reason": "not_deleting"}

    try:
        from app.services.call_imports.discovered_running_cache import (
            clear_discovered_running_cache,
        )

        clear_discovered_running_cache(evaluation_id)

        progress = 0
        row_sessions = _catalog_and_shard_sessions(catalog_db)
        try:
            for session, _ in row_sessions:
                deleted = _delete_one_page_eval_rows(session, evaluation_id)
                if deleted:
                    progress = deleted
                    break
        finally:
            _close_extra_sessions(row_sessions)

        evaluation.updated_at = datetime.now(timezone.utc)
        catalog_db.commit()

        if progress or _eval_rows_remain(catalog_db, evaluation_id):
            refresh_eval_delete_lock(evaluation_id)
            _schedule_eval_delete_continuation(
                evaluation_id, organization_id, call_import_id
            )
            return {"status": "continuing", "deleted_rows": progress}

        if _artifacts_remain(catalog_db, evaluation_id):
            _delete_catalog_artifacts_for_eval(catalog_db, evaluation_id)
            refresh_eval_delete_lock(evaluation_id)
            _schedule_eval_delete_continuation(
                evaluation_id, organization_id, call_import_id
            )
            return {"status": "continuing", "deleted_artifacts": True}

        catalog_db.execute(
            delete(CallImportEvaluation).where(CallImportEvaluation.id == evaluation_id)
        )
        catalog_db.commit()

        from app.services.call_imports.eval_progress_buffer import (
            delete as delete_eval_counters,
        )

        delete_eval_counters(evaluation_id)
        clear_eval_delete_lock(evaluation_id)
        logger.info("Deleted call_import_evaluation {}", evaluation_id)
        return {"status": "completed"}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Chunk failed during evaluation delete {}", evaluation_id)
        catalog_db.rollback()
        evaluation = (
            catalog_db.query(CallImportEvaluation)
            .filter(CallImportEvaluation.id == evaluation_id)
            .first()
        )
        if evaluation is not None:
            evaluation.status = EVAL_DELETING_STATUS
            evaluation.error_message = f"Failed to delete evaluation: {exc}"
            evaluation.updated_at = datetime.now(timezone.utc)
            catalog_db.commit()
        clear_eval_delete_lock(evaluation_id)
        return {"status": "error", "error": str(exc)}