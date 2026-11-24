"""Guarded evaluation status updates so teardown ``deleting`` is not clobbered."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import func, update
from sqlalchemy.orm import Session

from app.models.database import CallImportEvaluation
from app.services.call_imports.evaluation_teardown import EVAL_DELETING_STATUS


def _not_deleting_predicate():
    return (
        func.coalesce(func.lower(func.trim(CallImportEvaluation.status)), "")
        != EVAL_DELETING_STATUS
    )


def update_evaluation_unless_deleting(
    db: Session,
    evaluation_id: UUID,
    values: Mapping[str, Any],
) -> bool:
    """Apply ``values`` only when the row is not ``deleting``. Returns whether a row matched."""
    if not values:
        return False
    result = db.execute(
        update(CallImportEvaluation)
        .where(
            CallImportEvaluation.id == evaluation_id,
            _not_deleting_predicate(),
        )
        .values(**dict(values))
        .execution_options(synchronize_session=False)
    )
    return bool(result.rowcount)


def expire_evaluation_orm(db: Session, evaluation: CallImportEvaluation | None) -> None:
    if evaluation is not None:
        db.expire(evaluation)


def evaluation_status_is_deleting(db: Session, evaluation_id: UUID) -> bool:
    status = (
        db.query(CallImportEvaluation.status)
        .filter(CallImportEvaluation.id == evaluation_id)
        .scalar()
    )
    return (status or "").strip().lower() == EVAL_DELETING_STATUS