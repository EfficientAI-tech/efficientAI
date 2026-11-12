"""Abort evaluations that have been running for 24 hours."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from itertools import groupby
from uuid import UUID

from loguru import logger
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.database import CallImportEvaluation
from app.workers.config import EVAL_CONTROL_QUEUE, PLATFORM_WORKER_QUEUE, celery_app
from app.workers.tasks.evaluate_call_import_row_core import (
    AUTO_ABORTED_STATUS,
    EVAL_AUTO_ABORTED_ERROR,
)

STALE_RUNNING_HOURS = 24


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def stale_cutoff(now: datetime | None = None) -> datetime:
    moment = _as_utc(now or datetime.now(timezone.utc))
    return moment - timedelta(hours=STALE_RUNNING_HOURS)


def list_stale_running_evaluation_ids(
    db: Session,
    *,
    now: datetime | None = None,
) -> list[tuple[UUID, UUID]]:
    """Parent ids for running evaluations older than 24 hours, any workspace."""
    cutoff = stale_cutoff(now)
    age = func.coalesce(
        CallImportEvaluation.started_at,
        CallImportEvaluation.created_at,
    )
    rows = (
        db.query(CallImportEvaluation.organization_id, CallImportEvaluation.id)
        .filter(
            CallImportEvaluation.status == "running",
            or_(age.is_(None), age <= cutoff),
        )
        .order_by(CallImportEvaluation.organization_id, CallImportEvaluation.id)
        .all()
    )
    return [
        (org_id, evaluation_id)
        for org_id, evaluation_id in rows
        if org_id is not None
    ]


def evaluation_is_stale_running(
    db: Session,
    evaluation_id: UUID,
    *,
    now: datetime | None = None,
) -> bool:
    row = (
        db.query(
            CallImportEvaluation.status,
            CallImportEvaluation.started_at,
            CallImportEvaluation.created_at,
        )
        .filter(CallImportEvaluation.id == evaluation_id)
        .one_or_none()
    )
    if row is None:
        return False
    status, started_at, created_at = row
    if (status or "").strip().lower() != "running":
        return False
    age = started_at or created_at
    if age is None:
        return True
    return _as_utc(age) <= stale_cutoff(now)


def enqueue_stale_evaluation_aborts(
    db: Session,
    *,
    now: datetime | None = None,
) -> int:
    from app.services.call_imports.evaluation_bulk_op import (
        clear_evaluation_bulk_operation,
        try_set_evaluation_bulk_operation,
    )

    enqueued = 0
    for org_id, group in groupby(
        list_stale_running_evaluation_ids(db, now=now),
        key=lambda item: item[0],
    ):
        org_count = 0
        for _, evaluation_id in group:
            if not try_set_evaluation_bulk_operation(evaluation_id, "abort"):
                continue
            try:
                auto_abort_stale_evaluation_task.delay(str(evaluation_id))
            except Exception:
                clear_evaluation_bulk_operation(evaluation_id)
                logger.exception(
                    "Failed to enqueue auto-abort for evaluation {}",
                    evaluation_id,
                )
                continue
            org_count += 1
        if org_count:
            logger.info(
                "Enqueued auto-abort for {} evaluations in organization {}",
                org_count,
                org_id,
            )
            enqueued += org_count
    return enqueued


@celery_app.task(
    name="sweep_stale_running_evaluations",
    queue=PLATFORM_WORKER_QUEUE,
)
def sweep_stale_running_evaluations_task() -> int:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        return enqueue_stale_evaluation_aborts(db)
    finally:
        db.close()


@celery_app.task(
    name="auto_abort_stale_evaluation",
    queue=EVAL_CONTROL_QUEUE,
)
def auto_abort_stale_evaluation_task(evaluation_id: str) -> dict:
    from app.database import SessionLocal
    from app.services.call_imports.bulk_ops import execute_evaluation_cancel
    from app.services.call_imports.evaluation_bulk_op import (
        clear_evaluation_bulk_operation,
    )

    evaluation_uuid = UUID(evaluation_id)
    db = SessionLocal()
    try:
        if not evaluation_is_stale_running(db, evaluation_uuid):
            return {
                "evaluation_id": evaluation_id,
                "cancelled": 0,
                "skipped": True,
            }
        return execute_evaluation_cancel(
            db,
            evaluation_uuid,
            mode="abort",
            row_error_message=EVAL_AUTO_ABORTED_ERROR,
            sticky_status=AUTO_ABORTED_STATUS,
        )
    finally:
        clear_evaluation_bulk_operation(evaluation_uuid)
        db.close()
