"""Round-robin fair dispatch for standalone call-import diarization."""

from __future__ import annotations

from typing import List
from uuid import UUID

import redis
from loguru import logger
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.database import CallImport, CallImportRow
from app.workers.concurrency.diarization_dispatch import (
    _try_dispatch_single_diarization_row,
    _MISSING_PARAMS_ERROR,
    get_row_diarization_params,
    pop_row_diarization_params,
)
from app.workers.concurrency.eval_dispatch import DIARIZATION_QUEUE
from app.workers.config import celery_app

_RR_CURSOR_KEY = "diarisation:fair:rr_cursor"
_WS_CALL_IMPORT_RR_CURSOR_KEY_PREFIX = "diarisation:fair:rr_cursor:ws:"

_redis_client: redis.Redis | None = None


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


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
        logger.warning("Failed to persist diarization fair-dispatch RR cursor: {}", exc)


def _workspace_call_import_rr_cursor_key(workspace_id: UUID | str) -> str:
    return f"{_WS_CALL_IMPORT_RR_CURSOR_KEY_PREFIX}{workspace_id}"


def _get_workspace_call_import_rr_cursor(workspace_id: UUID) -> int:
    try:
        raw = _get_redis().get(_workspace_call_import_rr_cursor_key(workspace_id))
        return int(raw or 0)
    except (redis.RedisError, ValueError, TypeError):
        return 0


def _set_workspace_call_import_rr_cursor(workspace_id: UUID, cursor: int) -> None:
    try:
        _get_redis().set(
            _workspace_call_import_rr_cursor_key(workspace_id),
            str(max(0, cursor)),
        )
    except redis.RedisError as exc:
        logger.warning(
            "Failed to persist workspace diarization RR cursor for {}: {}",
            workspace_id,
            exc,
        )


def _workspaces_with_pending_diarization(db: Session) -> List[UUID]:
    rows = (
        db.query(CallImport.workspace_id)
        .join(CallImportRow, CallImportRow.call_import_id == CallImport.id)
        .filter(
            CallImportRow.diarised_transcript_status == "pending",
            CallImportRow.celery_task_id.is_(None),
        )
        .distinct()
        .all()
    )
    return sorted({row[0] for row in rows if row[0] is not None})


def _call_imports_with_pending_diarization(
    db: Session,
    workspace_id: UUID,
) -> List[UUID]:
    rows = (
        db.query(CallImport.id)
        .join(CallImportRow, CallImportRow.call_import_id == CallImport.id)
        .filter(
            CallImport.workspace_id == workspace_id,
            CallImportRow.diarised_transcript_status == "pending",
            CallImportRow.celery_task_id.is_(None),
        )
        .distinct()
        .all()
    )
    return sorted({row[0] for row in rows if row[0] is not None})


def _pending_row_for_call_import(
    db: Session,
    call_import_id: UUID,
) -> tuple[CallImportRow, CallImport] | None:
    row = (
        db.query(CallImportRow, CallImport)
        .join(CallImport, CallImport.id == CallImportRow.call_import_id)
        .filter(
            CallImport.id == call_import_id,
            CallImportRow.diarised_transcript_status == "pending",
            CallImportRow.celery_task_id.is_(None),
        )
        .order_by(CallImportRow.created_at.asc())
        .first()
    )
    if row is None:
        return None
    return row[0], row[1]


def _dispatch_batch_for_workspace(
    db: Session,
    workspace_id: UUID,
    *,
    batch_size: int,
) -> int:
    call_imports = _call_imports_with_pending_diarization(db, workspace_id)
    if not call_imports:
        return 0

    cursor = _get_workspace_call_import_rr_cursor(workspace_id) % len(call_imports)
    dispatched = 0
    skips = 0

    while dispatched < batch_size and skips < len(call_imports):
        call_import_id = call_imports[cursor]
        pending = _pending_row_for_call_import(db, call_import_id)
        if pending is None:
            skips += 1
            cursor = (cursor + 1) % len(call_imports)
            continue

        row, call_import = pending
        params = get_row_diarization_params(row.id)
        if not params:
            row.diarised_transcript_status = "failed"
            row.diarised_transcript_error = _MISSING_PARAMS_ERROR
            db.commit()
            skips += 1
            cursor = (cursor + 1) % len(call_imports)
            continue

        result = _try_dispatch_single_diarization_row(
            db=db,
            row=row,
            call_import=call_import,
            params=params,
        )
        if result == "dispatched":
            pop_row_diarization_params(row.id)
            dispatched += 1
            skips = 0
        elif result == "at_capacity":
            _set_workspace_call_import_rr_cursor(workspace_id, cursor)
            return dispatched
        else:
            skips += 1

        cursor = (cursor + 1) % len(call_imports)

    _set_workspace_call_import_rr_cursor(workspace_id, cursor)
    return dispatched


def schedule_fair_diarization_dispatch(
    *,
    max_workspace_turns: int = 1,
    countdown: int = 0,
) -> None:
    try:
        dispatch_fair_diarization_rows_task.apply_async(
            kwargs={"max_workspace_turns": max_workspace_turns},
            queue=DIARIZATION_QUEUE,
            countdown=countdown,
        )
    except Exception as exc:
        logger.warning("Failed to schedule fair diarization dispatch: {}", exc)


@celery_app.task(name="dispatch_fair_diarization_rows", queue=DIARIZATION_QUEUE)
def dispatch_fair_diarization_rows_task(max_workspace_turns: int = 1) -> dict:
    """Round-robin pending diarization rows across workspaces (batch K per turn)."""
    db = SessionLocal()
    try:
        workspaces = _workspaces_with_pending_diarization(db)
        if not workspaces:
            return {"status": "ok", "dispatched": 0, "workspaces": 0}

        batch_size = max(1, int(settings.DIARIZATION_FAIR_DISPATCH_BATCH_SIZE))
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
        logger.exception("dispatch_fair_diarization_rows failed")
        raise
    finally:
        db.close()


def finish_diarization_work_and_redispatch(celery_task_id: str) -> None:
    """Release a slot and schedule one fair diarization workspace turn."""
    from app.workers.concurrency.limits import release_eval_slot_for_celery_task

    release_eval_slot_for_celery_task(celery_task_id)
    schedule_fair_diarization_dispatch(max_workspace_turns=1)
