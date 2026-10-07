"""Redis lock for singleton alert evaluation (fail closed on Redis errors)."""

from __future__ import annotations

import os

import redis
from loguru import logger

from app.config import settings

_ALERT_EVAL_LOCK_KEY = "alerts:evaluate:lock"
_redis: redis.Redis | None = None


def _client() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


def _lock_ttl_seconds() -> int:
    raw = os.environ.get("ALERT_EVAL_LOCK_TTL_SECONDS", "280")
    try:
        return max(60, int(raw))
    except (TypeError, ValueError):
        return 280


def acquire_alert_evaluation_lock() -> bool:
    try:
        return bool(
            _client().set(
                _ALERT_EVAL_LOCK_KEY,
                "1",
                nx=True,
                ex=_lock_ttl_seconds(),
            )
        )
    except (redis.RedisError, ConnectionError, OSError) as exc:
        logger.warning("alert evaluation lock unavailable (skipping tick): {}", exc)
        return False


def release_alert_evaluation_lock() -> None:
    try:
        _client().delete(_ALERT_EVAL_LOCK_KEY)
    except redis.RedisError:
        pass
