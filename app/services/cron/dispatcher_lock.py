"""Redis locks for singleton cron dispatcher."""

from __future__ import annotations

import os

import redis
from loguru import logger

from app.config import settings

_DISPATCHER_LOCK_KEY = "cron:dispatcher:lock"
_DISPATCHER_LEADER_KEY = "cron:dispatcher:leader"
_redis: redis.Redis | None = None


def _client() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


def _lock_ttl_seconds() -> int:
    raw = os.environ.get("CRON_DISPATCH_LOCK_TTL_SECONDS", "55")
    try:
        return max(10, int(raw))
    except (TypeError, ValueError):
        return 55


def _leader_ttl_seconds() -> int:
    raw = os.environ.get("CRON_DISPATCH_LEADER_TTL_SECONDS", "300")
    try:
        return max(60, int(raw))
    except (TypeError, ValueError):
        return 300


def try_acquire_dispatcher_leader() -> bool:
    try:
        return bool(
            _client().set(
                _DISPATCHER_LEADER_KEY,
                "1",
                nx=True,
                ex=_leader_ttl_seconds(),
            )
        )
    except redis.RedisError as exc:
        logger.warning("cron dispatcher leader lock skipped: {}", exc)
        return False


def refresh_dispatcher_leader() -> None:
    try:
        _client().expire(_DISPATCHER_LEADER_KEY, _leader_ttl_seconds())
    except redis.RedisError:
        pass


def acquire_dispatcher_run_lock() -> bool:
    try:
        return bool(
            _client().set(
                _DISPATCHER_LOCK_KEY,
                "1",
                nx=True,
                ex=_lock_ttl_seconds(),
            )
        )
    except redis.RedisError as exc:
        logger.warning("cron dispatcher run lock skipped: {}", exc)
        return True


def release_dispatcher_run_lock() -> None:
    try:
        _client().delete(_DISPATCHER_LOCK_KEY)
    except redis.RedisError:
        pass
