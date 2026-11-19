"""API helpers to enqueue chunked evaluation-run deletes."""

from __future__ import annotations

from typing import List
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import CallImportEvaluation
from app.services.call_imports.delete_teardown_lock import eval_delete_lock_held
from app.services.call_imports.evaluation_teardown import EVAL_DELETING_STATUS


def _enqueue_evaluation_delete(
    evaluation_id: UUID,
    organization_id: UUID,
    call_import_id: UUID,
) -> None:
    from app.workers.tasks.call_import_bulk_ops import delete_call_import_evaluation_task

    if not eval_delete_lock_held(evaluation_id):
        delete_call_import_evaluation_task.delay(
            str(evaluation_id),
            str(organization_id),
            str(call_import_id),
        )


def begin_evaluation_delete(
    db: Session,
    evaluation: CallImportEvaluation,
) -> bool:
    """Mark deleting and enqueue teardown. Returns True if accepted."""
    status = (evaluation.status or "").strip().lower()
    if status == EVAL_DELETING_STATUS:
        _enqueue_evaluation_delete(
            evaluation.id,
            evaluation.organization_id,
            evaluation.call_import_id,
        )
        return True

    evaluation.status = EVAL_DELETING_STATUS
    evaluation.error_message = None
    db.commit()
    _enqueue_evaluation_delete(
        evaluation.id,
        evaluation.organization_id,
        evaluation.call_import_id,
    )
    return True


def begin_bulk_evaluation_delete(
    db: Session,
    rows: List[CallImportEvaluation],
) -> int:
    accepted = 0
    for row in rows:
        if begin_evaluation_delete(db, row):
            accepted += 1
    return accepted