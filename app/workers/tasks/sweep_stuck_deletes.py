"""Re-enqueue stale call-import and evaluation deletes (lookup only; no row deletes)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from loguru import logger
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.database import CallImport, CallImportEvaluation
from app.models.enums import CallImportStatus
from app.services.call_imports.delete_teardown_lock import (
    call_import_delete_lock_held,
    eval_delete_lock_held,
)
from app.services.call_imports.evaluation_teardown import EVAL_DELETING_STATUS
from app.services.call_imports.import_teardown import _FAILED_DELETE_PREFIX
from app.workers.config import celery_app

STALE_DELETE_SECONDS = 120
MAX_STUCK_ENQUEUE = 25


def _stale_cutoff(now: datetime | None = None) -> datetime:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment - timedelta(seconds=STALE_DELETE_SECONDS)


def list_stuck_call_imports(
    db: Session,
    *,
    now: datetime | None = None,
    limit: int = MAX_STUCK_ENQUEUE,
) -> list[tuple[UUID, UUID]]:
    cutoff = _stale_cutoff(now)
    rows = (
        db.query(CallImport.id, CallImport.organization_id)
        .filter(
            CallImport.updated_at <= cutoff,
            or_(
                CallImport.status == CallImportStatus.DELETING,
                and_(
                    CallImport.status == CallImportStatus.FAILED,
                    CallImport.error_message.like(f"{_FAILED_DELETE_PREFIX}%"),
                ),
            ),
        )
        .order_by(CallImport.updated_at.asc())
        .limit(limit)
        .all()
    )
    return [(row_id, org_id) for row_id, org_id in rows if row_id and org_id]


def list_stuck_evaluations(
    db: Session,
    *,
    now: datetime | None = None,
    limit: int = MAX_STUCK_ENQUEUE,
) -> list[tuple[UUID, UUID, UUID]]:
    cutoff = _stale_cutoff(now)
    rows = (
        db.query(
            CallImportEvaluation.id,
            CallImportEvaluation.organization_id,
            CallImportEvaluation.call_import_id,
        )
        .filter(
            CallImportEvaluation.status == EVAL_DELETING_STATUS,
            CallImportEvaluation.updated_at <= cutoff,
        )
        .order_by(CallImportEvaluation.updated_at.asc())
        .limit(limit)
        .all()
    )
    return [
        (eval_id, org_id, import_id)
        for eval_id, org_id, import_id in rows
        if eval_id and org_id and import_id
    ]


def enqueue_stuck_deletes(db: Session, *, now: datetime | None = None) -> int:
    from app.workers.tasks.call_import_bulk_ops import (
        delete_call_import_evaluation_task,
        delete_call_import_task,
    )

    enqueued = 0
    stuck_imports = list_stuck_call_imports(db, now=now, limit=MAX_STUCK_ENQUEUE)
    remaining = max(0, MAX_STUCK_ENQUEUE - len(stuck_imports))

    for call_import_id, organization_id in stuck_imports:
        if call_import_delete_lock_held(call_import_id):
            continue
        try:
            delete_call_import_task.delay(str(call_import_id), str(organization_id))
            enqueued += 1
        except Exception:
            logger.exception(
                "Failed to enqueue stuck delete for call_import {}",
                call_import_id,
            )

    for evaluation_id, organization_id, call_import_id in list_stuck_evaluations(
        db, now=now, limit=remaining
    ):
        if eval_delete_lock_held(evaluation_id):
            continue
        try:
            delete_call_import_evaluation_task.delay(
                str(evaluation_id),
                str(organization_id),
                str(call_import_id),
            )
            enqueued += 1
        except Exception:
            logger.exception(
                "Failed to enqueue stuck delete for evaluation {}",
                evaluation_id,
            )
    return enqueued


@celery_app.task(name="sweep_stuck_deletes")
def sweep_stuck_deletes_task() -> int:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        return enqueue_stuck_deletes(db)
    finally:
        db.close()