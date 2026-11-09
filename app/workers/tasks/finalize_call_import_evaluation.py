"""Close an evaluation run once no rows are pending or running.

Enqueued (deduplicated) by the worker hot path when the Redis ``remaining``
counter reaches 0, by the progress flusher, and by the periodic catalog sweep.
Always does a fenced shard recount first, so it never trusts buffered
counters to decide that a run is finished.
"""

from __future__ import annotations

from uuid import UUID

from loguru import logger

from app.workers.config import EVAL_CONTROL_QUEUE, celery_app


@celery_app.task(
    name="finalize_call_import_evaluation",
    queue=EVAL_CONTROL_QUEUE,
)
def finalize_call_import_evaluation_task(evaluation_id: str) -> dict:
    from app.database import SessionLocal
    from app.services.call_imports.evaluation_bulk_op import (
        get_evaluation_bulk_operation,
    )
    from app.workers.tasks.evaluate_call_import_row_core import (
        finalize_evaluation_progress,
    )

    evaluation_uuid = UUID(str(evaluation_id))
    bulk_op = get_evaluation_bulk_operation(evaluation_uuid)
    if bulk_op:
        # The bulk op ends with its own fenced recount + status rollup; the
        # periodic sweep re-checks anything it leaves running.
        return {"evaluation_id": str(evaluation_uuid), "skipped": bulk_op}

    db = SessionLocal()
    try:
        outcome = finalize_evaluation_progress(db, evaluation_uuid)
    except Exception:
        db.rollback()
        logger.exception("finalize_call_import_evaluation failed for {}", evaluation_uuid)
        raise
    finally:
        db.close()
    return {"evaluation_id": str(evaluation_uuid), "outcome": outcome}
