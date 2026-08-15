"""Redis cache for org usage read endpoints (summary, breakdown, filters)."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Optional
from uuid import UUID

import redis
from loguru import logger

from app.config import settings
from app.services.usage.access import UsageAccessResult

_redis: redis.Redis | None = None


def _client() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


def cache_ttl_seconds() -> int:
    raw = os.environ.get("USAGE_READ_CACHE_TTL_SECONDS", "90")
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 90


def cache_key_for(access: UsageAccessResult, **params: Any) -> str:
    payload: dict[str, Any] = {
        "display_start": access.display_start.isoformat(),
        "display_end": access.display_end.isoformat(),
        "filter_start": access.filter_start.isoformat(),
        "filter_end": access.filter_end.isoformat(),
        "enforced_floor": (
            access.enforced_filter_floor.isoformat()
            if access.enforced_filter_floor
            else None
        ),
        "range_clamped": access.range_clamped,
        "policy": access.policy.as_dict(),
    }
    for key, value in sorted(params.items()):
        if value is None:
            payload[key] = None
        elif isinstance(value, UUID):
            payload[key] = str(value)
        else:
            payload[key] = value
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()
    return digest[:32]


def _redis_key(organization_id: UUID, endpoint: str, cache_key: str) -> str:
    return f"usage:read:{organization_id}:{endpoint}:{cache_key}"


def get_cached_response(
    organization_id: UUID,
    endpoint: str,
    cache_key: str,
) -> Optional[dict[str, Any]]:
    ttl = cache_ttl_seconds()
    if ttl <= 0:
        return None
    try:
        raw = _client().get(_redis_key(organization_id, endpoint, cache_key))
        if not raw:
            return None
        return json.loads(raw)
    except (redis.RedisError, json.JSONDecodeError) as exc:
        logger.debug("usage read cache miss/error org={} endpoint={}: {}", organization_id, endpoint, exc)
        return None


def set_cached_response(
    organization_id: UUID,
    endpoint: str,
    cache_key: str,
    payload: dict[str, Any],
) -> None:
    ttl = cache_ttl_seconds()
    if ttl <= 0:
        return
    try:
        _client().set(
            _redis_key(organization_id, endpoint, cache_key),
            json.dumps(payload, default=str),
            ex=ttl,
        )
    except redis.RedisError as exc:
        logger.debug("usage read cache set failed org={}: {}", organization_id, exc)


def invalidate_org_usage_read_cache(organization_id: UUID) -> int:
    pattern = f"usage:read:{organization_id}:*"
    deleted = 0
    try:
        client = _client()
        batch: list[str] = []
        for key in client.scan_iter(match=pattern, count=200):
            batch.append(key)
            if len(batch) >= 200:
                deleted += client.delete(*batch)
                batch.clear()
        if batch:
            deleted += client.delete(*batch)
    except redis.RedisError as exc:
        logger.warning("usage read cache invalidate failed org={}: {}", organization_id, exc)
    return deleted
