"""Access-token revocation via Redis (with in-memory fallback for tests)."""

from __future__ import annotations

import logging
import time
from typing import Dict

import redis

from app.config import settings

logger = logging.getLogger(__name__)

_redis_client: redis.Redis | None = None
_in_memory_revoked: Dict[str, float] = {}


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def _purge_expired_in_memory() -> None:
    now = time.time()
    expired = [jti for jti, exp in _in_memory_revoked.items() if exp <= now]
    for jti in expired:
        _in_memory_revoked.pop(jti, None)


def revoke_access_jti(jti: str, ttl_seconds: int) -> None:
    """Blacklist an access token until its natural expiry."""
    ttl = max(int(ttl_seconds), 1)
    try:
        _get_redis().setex(f"revoked:jti:{jti}", ttl, "1")
    except redis.RedisError as exc:
        logger.warning("Redis unavailable for token revocation; using in-memory fallback: %s", exc)
        _in_memory_revoked[jti] = time.time() + ttl


def is_access_jti_revoked(jti: str) -> bool:
    if not jti:
        return False
    try:
        return bool(_get_redis().exists(f"revoked:jti:{jti}"))
    except redis.RedisError as exc:
        logger.warning("Redis unavailable for token revocation check; using in-memory fallback: %s", exc)
        _purge_expired_in_memory()
        exp = _in_memory_revoked.get(jti)
        return exp is not None and exp > time.time()
