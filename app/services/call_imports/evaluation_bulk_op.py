"""Redis-backed lock for in-flight bulk evaluation operations (abort, retry, etc.)."""

from __future__ import annotations

from typing import Literal, Optional
from uuid import UUID

import redis
from loguru import logger

from app.config import settings

BulkEvaluationOperation = Literal["abort", "force_fail_pending", "retry"]

_BULK_OP_KEY_PREFIX = "eval:bulk_op:"
_BULK_OP_TTL_SECONDS = 60 * 60

_redis_client: redis.Redis | None = None


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def _bulk_op_key(evaluation_id: UUID | str) -> str:
    return f"{_BULK_OP_KEY_PREFIX}{evaluation_id}"


def get_evaluation_bulk_operation(
    evaluation_id: UUID | str,
) -> Optional[str]:
    """Return the active bulk operation name, if any."""
    try:
        value = _get_redis().get(_bulk_op_key(evaluation_id))
        return str(value) if value else None
    except redis.RedisError as exc:
        logger.warning(
            "Failed to read bulk operation for evaluation {}: {}",
            evaluation_id,
            exc,
        )
        return None


def try_set_evaluation_bulk_operation(
    evaluation_id: UUID | str,
    operation: BulkEvaluationOperation,
) -> bool:
    """Atomically claim the bulk-operation slot. Returns False if already held."""
    try:
        return bool(
            _get_redis().set(
                _bulk_op_key(evaluation_id),
                operation,
                nx=True,
                ex=_BULK_OP_TTL_SECONDS,
            )
        )
    except redis.RedisError as exc:
        logger.warning(
            "Failed to set bulk operation {} for evaluation {}: {}",
            operation,
            evaluation_id,
            exc,
        )
        return True


def clear_evaluation_bulk_operation(evaluation_id: UUID | str) -> None:
    """Release the bulk-operation slot after the worker finishes."""
    try:
        _get_redis().delete(_bulk_op_key(evaluation_id))
    except redis.RedisError as exc:
        logger.warning(
            "Failed to clear bulk operation for evaluation {}: {}",
            evaluation_id,
            exc,
        )
