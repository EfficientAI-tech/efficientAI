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
    DISPATCH_QUEUE,
    _needs_transcribe_for_eval,
    _try_dispatch_single_row,
)
from app.workers.config import celery_app

_RR_CURSOR_KEY = "eval:fair:rr_cursor"
_WS_EVAL_RR_CURSOR_KEY_PREFIX = "eval:fair:rr_cursor:ws:"
_RESTRICTED_ROW_KEY_PREFIX = "eval:restricted:row:"
_TRANSCRIBE_OVERWRITE_KEY_PREFIX = "eval:transcribe_overwrite:"
_RESTRICTED_ROW_TTL_SECONDS = 20 * 60
_DISPATCH_DEDUPE_KEY = "eval:fair:dispatch_dedupe"
_DISPATCH_AT_CAPACITY_BACKOFF_SECONDS = 15

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


def get_row_restricted_metrics(eval_row_id: UUID | str) -> Optional[List[str]]:
    """Read metric-subset retry ids without removing them from Redis."""
    key = f"{_RESTRICTED_ROW_KEY_PREFIX}{eval_row_id}"
    try:
        raw = _get_redis().get(key)
        if not raw:
            return None
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


def clear_row_restricted_metrics(eval_row_id: UUID | str) -> None:
    """Remove stored metric-subset retry ids after a successful dispatch."""
    key = f"{_RESTRICTED_ROW_KEY_PREFIX}{eval_row_id}"
    try:
        _get_redis().delete(key)
    except redis.RedisError as exc:
        logger.warning(
            "Failed to clear restricted metrics for eval row {}: {}",
            eval_row_id,
            exc,
        )


def pop_row_restricted_metrics(eval_row_id: UUID | str) -> Optional[List[str]]:
    """Atomically read and remove metric-subset retry ids."""
    restricted_metric_ids = get_row_restricted_metrics(eval_row_id)
    if restricted_metric_ids is not None:
        clear_row_restricted_metrics(eval_row_id)
    return restricted_metric_ids


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


def _workspace_eval_rr_cursor_key(workspace_id: UUID | str) -> str:
    return f"{_WS_EVAL_RR_CURSOR_KEY_PREFIX}{workspace_id}"


def _get_workspace_eval_rr_cursor(workspace_id: UUID) -> int:
    try:
        raw = _get_redis().get(_workspace_eval_rr_cursor_key(workspace_id))
        return int(raw or 0)
    except (redis.RedisError, ValueError, TypeError):
        return 0


def _set_workspace_eval_rr_cursor(workspace_id: UUID, cursor: int) -> None:
    try:
        _get_redis().set(
            _workspace_eval_rr_cursor_key(workspace_id),
            str(max(0, cursor)),
        )
    except redis.RedisError as exc:
        logger.warning(
            "Failed to persist workspace eval RR cursor for {}: {}",
            workspace_id,
            exc,
        )


def _workspaces_with_pending_rows(db: Session) -> List[UUID]:
    rows = (
        db.query(CallImportEvaluation.workspace_id)
        .join(
            CallImportEvaluationRow,
            CallImportEvaluationRow.evaluation_id == CallImportEvaluation.id,
        )
        .filter(
            # Pending rows are authoritative — a run can stay ``partial``
            # (or even ``completed``) while retry resets rows back to
            # ``pending`` before rollup catches up.
            CallImportEvaluation.status != "cancelled",
            CallImportEvaluationRow.status == "pending",
            CallImportEvaluationRow.celery_task_id.is_(None),
        )
        .distinct()
        .all()
    )
    workspace_ids = sorted({row[0] for row in rows if row[0] is not None})
    return workspace_ids


def _evaluations_with_pending_rows(
    db: Session,
    workspace_id: UUID,
) -> List[UUID]:
    rows = (
        db.query(CallImportEvaluation.id)
        .join(
            CallImportEvaluationRow,
            CallImportEvaluationRow.evaluation_id == CallImportEvaluation.id,
        )
        .filter(
            CallImportEvaluation.workspace_id == workspace_id,
            CallImportEvaluation.status != "cancelled",
            CallImportEvaluationRow.status == "pending",
            CallImportEvaluationRow.celery_task_id.is_(None),
        )
        .distinct()
        .all()
    )
    return sorted({row[0] for row in rows if row[0] is not None})


def _pending_rows_for_evaluation(
    db: Session,
    evaluation_id: UUID,
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
            CallImportEvaluation.id == evaluation_id,
            CallImportEvaluation.status != "cancelled",
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
) -> tuple[int, bool, int]:
    """Dispatch up to ``batch_size`` pending rows for one workspace turn.

    Returns ``(dispatched_count, hit_capacity, backoff_seconds)``.
    """
    evaluations = _evaluations_with_pending_rows(db, workspace_id)
    if not evaluations:
        return 0, False, 0

    cursor = _get_workspace_eval_rr_cursor(workspace_id) % len(evaluations)
    dispatched = 0
    skips = 0
    hit_capacity = False
    backoff_seconds = 0

    while dispatched < batch_size and skips < len(evaluations):
        evaluation_id = evaluations[cursor]
        pending = _pending_rows_for_evaluation(
            db,
            evaluation_id,
            limit=max(1, batch_size - dispatched),
        )
        if not pending:
            skips += 1
            cursor = (cursor + 1) % len(evaluations)
            continue

        evaluation_dispatched = False
        for eval_row, source_row, evaluation in pending:
            restricted_metric_ids = get_row_restricted_metrics(eval_row.id)
            transcribe_overwrite = evaluation_transcribe_overwrite(evaluation.id)
            outcome = _try_dispatch_single_row(
                db=db,
                evaluation=evaluation,
                eval_row=eval_row,
                source_row=source_row,
                restricted_metric_ids=restricted_metric_ids,
                transcribe_overwrite=transcribe_overwrite,
                auto_transcribe=True,
            )
            if outcome.result == "dispatched":
                clear_row_restricted_metrics(eval_row.id)
                dispatched += 1
                evaluation_dispatched = True
                skips = 0
                if evaluation.status == "pending":
                    evaluation.status = "running"
                    db.commit()
                break
            if outcome.result in ("at_capacity", "credential_throttled"):
                hit_capacity = True
                if outcome.result == "credential_throttled":
                    backoff_seconds = max(backoff_seconds, outcome.wait_seconds)
                else:
                    backoff_seconds = max(
                        backoff_seconds, _DISPATCH_AT_CAPACITY_BACKOFF_SECONDS
                    )
                _set_workspace_eval_rr_cursor(workspace_id, cursor)
                return dispatched, hit_capacity, backoff_seconds

        if not evaluation_dispatched:
            skips += 1

        cursor = (cursor + 1) % len(evaluations)

    _set_workspace_eval_rr_cursor(workspace_id, cursor)
    return dispatched, hit_capacity, backoff_seconds


def _schedule_dispatch_deduped(
    *,
    max_workspace_turns: int = 1,
    countdown: int = 0,
) -> bool:
    """Schedule dispatch unless an identical backoff turn is already queued."""
    ttl = max(3, countdown + 2)
    try:
        if not _get_redis().set(
            _DISPATCH_DEDUPE_KEY,
            "1",
            nx=True,
            ex=ttl,
        ):
            return False
    except redis.RedisError as exc:
        logger.warning("Fair dispatch dedupe check failed: {}", exc)
    schedule_fair_dispatch(
        max_workspace_turns=max_workspace_turns,
        countdown=countdown,
        _skip_dedupe=True,
    )
    return True


def schedule_fair_dispatch(
    *,
    max_workspace_turns: int = 1,
    countdown: int = 0,
    _skip_dedupe: bool = False,
) -> None:
    """Schedule global workspace round-robin eval dispatch.

    ``max_workspace_turns``:
      * ``1`` — one workspace turn (up to batch K rows) after a task completes.
      * higher — fill capacity across workspaces (eval create / catch-up).
    """
    if not _skip_dedupe and countdown > 0:
        _schedule_dispatch_deduped(
            max_workspace_turns=max_workspace_turns,
            countdown=countdown,
        )
        return
    try:
        dispatch_fair_eval_rows_task.apply_async(
            kwargs={"max_workspace_turns": max_workspace_turns},
            queue=DISPATCH_QUEUE,
            countdown=countdown,
        )
    except Exception as exc:
        logger.warning("Failed to schedule fair eval dispatch: {}", exc)


@celery_app.task(name="dispatch_fair_eval_rows", queue=DISPATCH_QUEUE)
def dispatch_fair_eval_rows_task(max_workspace_turns: int = 1) -> dict:
    """Round-robin pending eval rows across workspaces (batch K per turn)."""
    db = SessionLocal()
    total_dispatched = 0
    hit_capacity = False
    try:
        workspaces = _workspaces_with_pending_rows(db)
        if not workspaces:
            return {"status": "ok", "dispatched": 0, "workspaces": 0}

        batch_size = max(1, int(settings.EVAL_FAIR_DISPATCH_BATCH_SIZE))
        max_turns = max(1, int(max_workspace_turns))

        cursor = _get_rr_cursor() % len(workspaces)
        turns_served = 0
        skips = 0
        backoff_seconds = 0

        while turns_served < max_turns and skips < len(workspaces):
            workspace_id = workspaces[cursor]
            dispatched, workspace_at_capacity, workspace_backoff = (
                _dispatch_batch_for_workspace(
                    db,
                    workspace_id,
                    batch_size=batch_size,
                )
            )
            hit_capacity = hit_capacity or workspace_at_capacity
            if workspace_backoff > 0:
                backoff_seconds = max(backoff_seconds, workspace_backoff)
            if dispatched > 0:
                total_dispatched += dispatched
                turns_served += 1
                skips = 0
                cursor = (cursor + 1) % len(workspaces)
                _set_rr_cursor(cursor)
            else:
                skips += 1
                cursor = (cursor + 1) % len(workspaces)

        if hit_capacity and _workspaces_with_pending_rows(db):
            _schedule_dispatch_deduped(
                max_workspace_turns=1,
                countdown=backoff_seconds or _DISPATCH_AT_CAPACITY_BACKOFF_SECONDS,
            )

        return {
            "status": "ok",
            "dispatched": total_dispatched,
            "workspaces": len(workspaces),
            "turns_served": turns_served,
            "batch_size": batch_size,
            "at_capacity": hit_capacity,
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


def read_fair_dispatch_state() -> dict:
    """Snapshot Redis fair-dispatch scheduler metadata for operator diagnostics."""
    try:
        client = _get_redis()
        dispatch_dedupe_active = bool(client.exists(_DISPATCH_DEDUPE_KEY))
    except redis.RedisError:
        dispatch_dedupe_active = False
    return {
        "global_rr_cursor": _get_rr_cursor(),
        "dispatch_dedupe_active": dispatch_dedupe_active,
        "dispatch_queue": DISPATCH_QUEUE,
        "at_capacity_backoff_seconds": _DISPATCH_AT_CAPACITY_BACKOFF_SECONDS,
    }


def read_workspace_eval_rr_cursor(workspace_id: UUID) -> int:
    return _get_workspace_eval_rr_cursor(workspace_id)
