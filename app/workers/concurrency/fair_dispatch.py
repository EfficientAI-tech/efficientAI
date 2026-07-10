"""Round-robin fair dispatch for call-import evaluations across workspaces."""

from __future__ import annotations

import json
from typing import List, Optional
from uuid import UUID

import redis
from loguru import logger
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.database import (
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
)
from app.workers.concurrency.eval_dispatch import (
    EVALUATIONS_QUEUE,
    _needs_transcribe_for_eval,
    _try_dispatch_single_row,
)
from app.workers.config import celery_app

_RR_CURSOR_KEY = "eval:fair:rr_cursor"
_RESTRICTED_ROW_KEY_PREFIX = "eval:restricted:row:"
_TRANSCRIBE_OVERWRITE_KEY_PREFIX = "eval:transcribe_overwrite:"
_RESTRICTED_ROW_TTL_SECONDS = 20 * 60

_redis_client: redis.Redis | None = None


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def store_row_restricted_metrics(
    eval_row_id: UUID | str,
    restricted_metric_ids: Optional[List[str]],
) -> None:
    """Persist metric-subset retry ids until the fair dispatcher enqueues the row."""
    if not restricted_metric_ids:
        return
    key = f"{_RESTRICTED_ROW_KEY_PREFIX}{eval_row_id}"
    try:
        _get_redis().setex(
            key,
            _RESTRICTED_ROW_TTL_SECONDS,
            json.dumps(restricted_metric_ids),
        )
    except redis.RedisError as exc:
        logger.warning(
            "Failed to store restricted metrics for eval row {}: {}",
            eval_row_id,
            exc,
        )


def store_evaluation_transcribe_overwrite(
    evaluation_id: UUID | str,
    *,
    overwrite: bool,
) -> None:
    if not overwrite:
        return
    key = f"{_TRANSCRIBE_OVERWRITE_KEY_PREFIX}{evaluation_id}"
    try:
        _get_redis().setex(key, _RESTRICTED_ROW_TTL_SECONDS, "1")
    except redis.RedisError as exc:
        logger.warning(
            "Failed to store transcribe_overwrite for evaluation {}: {}",
            evaluation_id,
            exc,
        )


def evaluation_transcribe_overwrite(evaluation_id: UUID | str) -> bool:
    key = f"{_TRANSCRIBE_OVERWRITE_KEY_PREFIX}{evaluation_id}"
    try:
        return _get_redis().get(key) == "1"
    except redis.RedisError:
        return False


def pop_row_restricted_metrics(eval_row_id: UUID | str) -> Optional[List[str]]:
    key = f"{_RESTRICTED_ROW_KEY_PREFIX}{eval_row_id}"
    try:
        client = _get_redis()
        raw = client.get(key)
        if not raw:
            return None
        client.delete(key)
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except (redis.RedisError, json.JSONDecodeError) as exc:
        logger.warning(
            "Failed to read restricted metrics for eval row {}: {}",
            eval_row_id,
            exc,
        )
    return None


def _get_rr_cursor() -> int:
    try:
        raw = _get_redis().get(_RR_CURSOR_KEY)
        return int(raw or 0)
    except (redis.RedisError, ValueError, TypeError):
        return 0


def _set_rr_cursor(cursor: int) -> None:
    try:
        _get_redis().set(_RR_CURSOR_KEY, str(max(0, cursor)))
    except redis.RedisError as exc:
        logger.warning("Failed to persist fair-dispatch RR cursor: {}", exc)


def _workspaces_with_pending_rows(db: Session) -> List[UUID]:
    rows = (
        db.query(CallImportEvaluation.workspace_id)
        .join(
            CallImportEvaluationRow,
            CallImportEvaluationRow.evaluation_id == CallImportEvaluation.id,
        )
        .filter(
            CallImportEvaluation.status.in_(("pending", "running")),
            CallImportEvaluationRow.status == "pending",
            CallImportEvaluationRow.celery_task_id.is_(None),
        )
        .distinct()
        .all()
    )
    workspace_ids = sorted({row[0] for row in rows if row[0] is not None})
    return workspace_ids


def _pending_rows_for_workspace(
    db: Session,
    workspace_id: UUID,
    *,
    limit: int,
) -> List[tuple[CallImportEvaluationRow, CallImportRow, CallImportEvaluation]]:
    return (
        db.query(CallImportEvaluationRow, CallImportRow, CallImportEvaluation)
        .join(
            CallImportRow,
            CallImportRow.id == CallImportEvaluationRow.call_import_row_id,
        )
        .join(
            CallImportEvaluation,
            CallImportEvaluation.id == CallImportEvaluationRow.evaluation_id,
        )
        .filter(
            CallImportEvaluation.workspace_id == workspace_id,
            CallImportEvaluation.status.in_(("pending", "running")),
            CallImportEvaluationRow.status == "pending",
            CallImportEvaluationRow.celery_task_id.is_(None),
        )
        .order_by(CallImportEvaluationRow.created_at.asc())
        .limit(limit)
        .all()
    )


def _dispatch_batch_for_workspace(
    db: Session,
    workspace_id: UUID,
    *,
    batch_size: int,
) -> int:
    """Dispatch up to ``batch_size`` pending rows for one workspace turn."""
    pending = _pending_rows_for_workspace(db, workspace_id, limit=batch_size)
    dispatched = 0
    for eval_row, source_row, evaluation in pending:
        restricted_metric_ids = pop_row_restricted_metrics(eval_row.id)
        transcribe_overwrite = evaluation_transcribe_overwrite(evaluation.id)
        if _try_dispatch_single_row(
            db=db,
            evaluation=evaluation,
            eval_row=eval_row,
            source_row=source_row,
            restricted_metric_ids=restricted_metric_ids,
            transcribe_overwrite=transcribe_overwrite,
            auto_transcribe=True,
        ):
            dispatched += 1
            if evaluation.status == "pending":
                evaluation.status = "running"
                db.commit()
        else:
            break
    return dispatched


def schedule_fair_dispatch(
    *,
    max_workspace_turns: int = 1,
    countdown: int = 0,
) -> None:
    """Schedule global workspace round-robin eval dispatch.

    ``max_workspace_turns``:
      * ``1`` — one workspace turn (up to batch K rows) after a task completes.
      * higher — fill capacity across workspaces (eval create / catch-up).
    """
    try:
        dispatch_fair_eval_rows_task.apply_async(
            kwargs={"max_workspace_turns": max_workspace_turns},
            queue=EVALUATIONS_QUEUE,
            countdown=countdown,
        )
    except Exception as exc:
        logger.warning("Failed to schedule fair eval dispatch: {}", exc)


@celery_app.task(name="dispatch_fair_eval_rows", queue=EVALUATIONS_QUEUE)
def dispatch_fair_eval_rows_task(max_workspace_turns: int = 1) -> dict:
    """Round-robin pending eval rows across workspaces (batch K per turn)."""
    db = SessionLocal()
    try:
        workspaces = _workspaces_with_pending_rows(db)
        if not workspaces:
            return {"status": "ok", "dispatched": 0, "workspaces": 0}

        batch_size = max(1, int(settings.EVAL_FAIR_DISPATCH_BATCH_SIZE))
        max_turns = max(1, int(max_workspace_turns))

        cursor = _get_rr_cursor() % len(workspaces)
        total_dispatched = 0
        turns_served = 0
        skips = 0

        while turns_served < max_turns and skips < len(workspaces):
            workspace_id = workspaces[cursor]
            dispatched = _dispatch_batch_for_workspace(
                db,
                workspace_id,
                batch_size=batch_size,
            )
            if dispatched > 0:
                total_dispatched += dispatched
                turns_served += 1
                skips = 0
                cursor = (cursor + 1) % len(workspaces)
                _set_rr_cursor(cursor)
            else:
                skips += 1
                cursor = (cursor + 1) % len(workspaces)

        return {
            "status": "ok",
            "dispatched": total_dispatched,
            "workspaces": len(workspaces),
            "turns_served": turns_served,
            "batch_size": batch_size,
        }
    except Exception:
        logger.exception("dispatch_fair_eval_rows failed")
        raise
    finally:
        db.close()


def finish_eval_work_and_redispatch(
    celery_task_id: str,
    *,
    restricted_metric_ids: Optional[List[str]] = None,
) -> None:
    """Release a slot and schedule one fair workspace turn."""
    from app.workers.concurrency.limits import release_eval_slot_for_celery_task

    release_eval_slot_for_celery_task(celery_task_id)
    if restricted_metric_ids:
        # Re-store for the next dispatch pick if this was a chained retry path.
        # Row-level storage is handled at enqueue; this kwarg is unused here.
        pass
    schedule_fair_dispatch(max_workspace_turns=1)
