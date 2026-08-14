"""Redis cache for resolved usage pricing rates."""

from __future__ import annotations

import json
from datetime import date
from typing import Optional
from uuid import UUID

import redis
from loguru import logger

from app.config import settings

PRICING_CACHE_TTL_SEC = 3600
PRICING_NULL_CACHE_TTL_SEC = 300
PRICING_CACHE_PREFIX = "usage:pricing"

_redis: redis.Redis | None = None


def _client() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


def pricing_cache_key(
    *,
    organization_id: UUID,
    model: str,
    usage_kind: str,
    usage_date: date,
) -> str:
    return (
        f"{PRICING_CACHE_PREFIX}:{organization_id}:{model}:"
        f"{usage_kind}:{usage_date.isoformat()}"
    )


def get_cached_rate_payload(key: str) -> Optional[dict]:
    try:
        raw = _client().get(key)
    except redis.RedisError as exc:
        logger.debug("pricing cache read skipped: {}", exc)
        return None
    if raw is None:
        return None
    if raw == "__null__":
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def set_cached_rate_payload(key: str, payload: Optional[dict]) -> None:
    try:
        value = "__null__" if not payload else json.dumps(payload)
        ttl = PRICING_NULL_CACHE_TTL_SEC if not payload else PRICING_CACHE_TTL_SEC
        _client().setex(key, ttl, value)
    except redis.RedisError as exc:
        logger.debug("pricing cache write skipped: {}", exc)


def invalidate_org_pricing_cache(organization_id: UUID) -> None:
    _invalidate_pricing_cache_pattern(f"{PRICING_CACHE_PREFIX}:{organization_id}:*")


def invalidate_all_pricing_cache() -> None:
    _invalidate_pricing_cache_pattern(f"{PRICING_CACHE_PREFIX}:*")


def _invalidate_pricing_cache_pattern(pattern: str) -> None:
    try:
        client = _client()
        cursor = 0
        while True:
            cursor, keys = client.scan(cursor=cursor, match=pattern, count=200)
            if keys:
                client.delete(*keys)
            if cursor == 0:
                break
    except redis.RedisError as exc:
        logger.debug("pricing cache invalidate skipped: {}", exc)
