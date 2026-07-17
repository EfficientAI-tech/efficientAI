"""Redis-backed completion counters with debounced catalog flush."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

import redis
from loguru import logger
from sqlalchemy.orm import Session

from app.config import settings

_redis: redis.Redis | None = None


def _client() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


def _eval_completed_key(evaluation_id: UUID | str) -> str:
    return f"eval:{evaluation_id}:completed"


def _eval_failed_key(evaluation_id: UUID | str) -> str:
    return f"eval:{evaluation_id}:failed"


def _import_completed_key(call_import_id: UUID | str) -> str:
    return f"import:{call_import_id}:completed"


def _import_failed_key(call_import_id: UUID | str) -> str:
    return f"import:{call_import_id}:failed"


def record_eval_row_terminal(
    evaluation_id: UUID | str,
    *,
    completed_delta: int = 0,
    failed_delta: int = 0,
) -> None:
    try:
        client = _client()
        if completed_delta:
            client.hincrby("eval:progress", _eval_completed_key(evaluation_id), completed_delta)
        if failed_delta:
            client.hincrby("eval:progress", _eval_failed_key(evaluation_id), failed_delta)
    except redis.RedisError as exc:
        logger.debug("eval progress counter skipped: {}", exc)


def record_import_row_terminal(
    call_import_id: UUID | str,
    *,
    completed_delta: int = 0,
    failed_delta: int = 0,
) -> None:
    try:
        client = _client()
        if completed_delta:
            client.hincrby(
                "import:progress",
                _import_completed_key(call_import_id),
                completed_delta,
            )
        if failed_delta:
            client.hincrby(
                "import:progress",
                _import_failed_key(call_import_id),
                failed_delta,
            )
    except redis.RedisError as exc:
        logger.debug("import progress counter skipped: {}", exc)


def read_eval_progress(evaluation_id: UUID | str) -> tuple[int, int]:
    try:
        client = _client()
        completed = int(client.hget("eval:progress", _eval_completed_key(evaluation_id)) or 0)
        failed = int(client.hget("eval:progress", _eval_failed_key(evaluation_id)) or 0)
        return completed, failed
    except redis.RedisError:
        return 0, 0


def flush_eval_progress_to_catalog(db: Session, evaluation_id: UUID) -> None:
    """Merge Redis deltas into catalog parent columns (best-effort)."""
    from app.models.database import CallImportEvaluation

    completed_delta, failed_delta = read_eval_progress(evaluation_id)
    if not completed_delta and not failed_delta:
        return
    evaluation = (
        db.query(CallImportEvaluation)
        .filter(CallImportEvaluation.id == evaluation_id)
        .first()
    )
    if evaluation is None:
        return
    evaluation.completed_rows = int(evaluation.completed_rows or 0) + completed_delta
    evaluation.failed_rows = int(evaluation.failed_rows or 0) + failed_delta
    db.flush()
    try:
        client = _client()
        if completed_delta:
            client.hincrby(
                "eval:progress",
                _eval_completed_key(evaluation_id),
                -completed_delta,
            )
        if failed_delta:
            client.hincrby(
                "eval:progress",
                _eval_failed_key(evaluation_id),
                -failed_delta,
            )
    except redis.RedisError:
        pass


def merge_eval_counters_for_ui(
    evaluation,
) -> tuple[int, int]:
    """Catalog counters plus unflushed Redis deltas for progress display."""
    completed = int(getattr(evaluation, "completed_rows", 0) or 0)
    failed = int(getattr(evaluation, "failed_rows", 0) or 0)
    rc, rf = read_eval_progress(evaluation.id)
    return completed + rc, failed + rf


def read_import_progress(call_import_id: UUID | str) -> tuple[int, int]:
    try:
        client = _client()
        completed = int(
            client.hget("import:progress", _import_completed_key(call_import_id)) or 0
        )
        failed = int(
            client.hget("import:progress", _import_failed_key(call_import_id)) or 0
        )
        return completed, failed
    except redis.RedisError:
        return 0, 0


def merge_import_counters_for_ui(call_import) -> tuple[int, int]:
    completed = int(getattr(call_import, "completed_rows", 0) or 0)
    failed = int(getattr(call_import, "failed_rows", 0) or 0)
    rc, rf = read_import_progress(call_import.id)
    return completed + rc, failed + rf


def record_import_row_status_transition(
    call_import_id: UUID | str,
    *,
    previous_status: str,
    new_status: str,
) -> None:
    from app.workers.tasks.evaluate_call_import_row_core import (
        counter_deltas_for_status_transition,
    )

    def _norm(value) -> str:
        raw = getattr(value, "value", value)
        return str(raw or "").strip().lower()

    completed_delta, failed_delta = counter_deltas_for_status_transition(
        _norm(previous_status),
        _norm(new_status),
    )
    if completed_delta or failed_delta:
        record_import_row_terminal(
            call_import_id,
            completed_delta=completed_delta,
            failed_delta=failed_delta,
        )


def flush_import_progress_to_catalog(db: Session, call_import_id: UUID) -> None:
    """Merge Redis import deltas into catalog parent (best-effort)."""
    from app.models.database import CallImport

    completed_delta, failed_delta = read_import_progress(call_import_id)
    if not completed_delta and not failed_delta:
        return
    call_import = (
        db.query(CallImport).filter(CallImport.id == call_import_id).first()
    )
    if call_import is None:
        return
    call_import.completed_rows = int(call_import.completed_rows or 0) + completed_delta
    call_import.failed_rows = int(call_import.failed_rows or 0) + failed_delta
    db.flush()
    try:
        client = _client()
        if completed_delta:
            client.hincrby(
                "import:progress",
                _import_completed_key(call_import_id),
                -completed_delta,
            )
        if failed_delta:
            client.hincrby(
                "import:progress",
                _import_failed_key(call_import_id),
                -failed_delta,
            )
    except redis.RedisError:
        pass
