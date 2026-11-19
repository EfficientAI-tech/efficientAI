"""Redis locks for resumable call-import and evaluation teardown."""

from __future__ import annotations

from uuid import UUID

import redis
from loguru import logger

from app.config import settings

_CALL_IMPORT_DELETE_LOCK_PREFIX = "call_import:delete:"
_EVAL_DELETE_LOCK_PREFIX = "eval:delete:"
_DELETE_LOCK_TTL_SECONDS = 120

_redis_client: redis.Redis | None = None


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def _call_import_delete_key(call_import_id: UUID | str) -> str:
    return f"{_CALL_IMPORT_DELETE_LOCK_PREFIX}{call_import_id}"


def _eval_delete_key(evaluation_id: UUID | str) -> str:
    return f"{_EVAL_DELETE_LOCK_PREFIX}{evaluation_id}"


def call_import_delete_lock_held(call_import_id: UUID | str) -> bool:
    try:
        return bool(_get_redis().exists(_call_import_delete_key(call_import_id)))
    except redis.RedisError as exc:
        logger.warning(
            "Failed to read call_import delete lock for {}: {}",
            call_import_id,
            exc,
        )
        return False


def ensure_call_import_delete_lock(call_import_id: UUID | str) -> bool:
    """Claim or refresh the delete lock (worker chunks). Returns False if another holder."""
    key = _call_import_delete_key(call_import_id)
    try:
        client = _get_redis()
        if client.set(key, "1", nx=True, ex=_DELETE_LOCK_TTL_SECONDS):
            return True
        if client.exists(key):
            client.expire(key, _DELETE_LOCK_TTL_SECONDS)
            return True
        return False
    except redis.RedisError as exc:
        logger.warning(
            "Failed to ensure call_import delete lock for {}: {}",
            call_import_id,
            exc,
        )
        return True


def clear_call_import_delete_lock(call_import_id: UUID | str) -> None:
    try:
        _get_redis().delete(_call_import_delete_key(call_import_id))
    except redis.RedisError as exc:
        logger.warning(
            "Failed to clear call_import delete lock for {}: {}",
            call_import_id,
            exc,
        )


def eval_delete_lock_held(evaluation_id: UUID | str) -> bool:
    try:
        return bool(_get_redis().exists(_eval_delete_key(evaluation_id)))
    except redis.RedisError as exc:
        logger.warning(
            "Failed to read eval delete lock for {}: {}",
            evaluation_id,
            exc,
        )
        return False


def ensure_eval_delete_lock(evaluation_id: UUID | str) -> bool:
    key = _eval_delete_key(evaluation_id)
    try:
        client = _get_redis()
        if client.set(key, "1", nx=True, ex=_DELETE_LOCK_TTL_SECONDS):
            return True
        if client.exists(key):
            client.expire(key, _DELETE_LOCK_TTL_SECONDS)
            return True
        return False
    except redis.RedisError as exc:
        logger.warning(
            "Failed to ensure eval delete lock for {}: {}",
            evaluation_id,
            exc,
        )
        return True


def clear_eval_delete_lock(evaluation_id: UUID | str) -> None:
    try:
        _get_redis().delete(_eval_delete_key(evaluation_id))
    except redis.RedisError as exc:
        logger.warning(
            "Failed to clear eval delete lock for {}: {}",
            evaluation_id,
            exc,
        )