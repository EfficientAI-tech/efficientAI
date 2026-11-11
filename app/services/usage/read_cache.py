"""Redis cache for org usage read endpoints (summary, breakdown, filters)."""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Callable, Optional
from uuid import UUID

import redis
from loguru import logger

from app.config import settings
from app.services.usage.access import UsageAccessResult

_redis: redis.Redis | None = None
_VERSION_TTL_SECONDS = 7 * 24 * 60 * 60
_STALE_TTL_SECONDS = 120
_LOCK_TTL_SECONDS = 10
_FOLLOWER_WAIT_SECONDS = 1.5


def _client() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


def _ttl_from_env(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return default


def cache_ttl_seconds() -> int:
    return _ttl_from_env("USAGE_READ_CACHE_TTL_SECONDS", 90)


def historical_cache_ttl_seconds() -> int:
    return _ttl_from_env("USAGE_HISTORICAL_READ_CACHE_TTL_SECONDS", 900)


def empty_cache_ttl_seconds() -> int:
    return _ttl_from_env("USAGE_EMPTY_READ_CACHE_TTL_SECONDS", 60)


def ttl_for_payload(*, historical: bool, empty: bool) -> int:
    ttl = historical_cache_ttl_seconds() if historical else cache_ttl_seconds()
    if empty:
        return min(ttl, empty_cache_ttl_seconds())
    return ttl


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


def _version_key(organization_id: UUID) -> str:
    return f"usage:read_ver:{organization_id}"


def _read_version(organization_id: UUID) -> str:
    try:
        raw = _client().get(_version_key(organization_id))
        return str(raw or "0")
    except redis.RedisError:
        return "0"


def read_cache_version(organization_id: UUID) -> str:
    """Epoch captured before a usage query. Writes must use this same value."""
    return _read_version(organization_id)


def _redis_key(
    organization_id: UUID,
    endpoint: str,
    cache_key: str,
    version: Optional[str] = None,
) -> str:
    current = version if version is not None else _read_version(organization_id)
    return f"usage:read:{organization_id}:v{current}:{endpoint}:{cache_key}"


def _stale_key(organization_id: UUID, endpoint: str, cache_key: str) -> str:
    return f"usage:read_stale:{organization_id}:{endpoint}:{cache_key}"


def _lock_key(organization_id: UUID, endpoint: str, cache_key: str) -> str:
    return f"usage:read_lock:{organization_id}:{endpoint}:{cache_key}"


def _is_empty_usage_payload(endpoint: str, payload: dict[str, Any]) -> bool:
    if endpoint == "summary":
        totals = payload.get("totals") or {}
        if int(totals.get("call_count") or 0) > 0:
            return False
        return not any(
            int(totals.get(field) or 0) > 0
            for field in (
                "prompt_tokens",
                "completion_tokens",
                "audio_seconds",
                "tts_characters",
            )
        )
    if endpoint == "breakdown":
        rows = payload.get("rows") or []
        if not rows:
            return True
        return not any(
            int(row.get("call_count") or 0) > 0
            or int(row.get("total_tokens") or 0) > 0
            or int(row.get("audio_seconds") or 0) > 0
            or int(row.get("tts_characters") or 0) > 0
            for row in rows
        )
    return False


def get_cached_response(
    organization_id: UUID,
    endpoint: str,
    cache_key: str,
    version: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    ttl = cache_ttl_seconds()
    if ttl <= 0:
        return None
    try:
        raw = _client().get(
            _redis_key(organization_id, endpoint, cache_key, version)
        )
        if not raw:
            return None
        payload = json.loads(raw)
        return payload
    except (redis.RedisError, json.JSONDecodeError) as exc:
        logger.debug("usage read cache miss/error org={} endpoint={}: {}", organization_id, endpoint, exc)
        return None


def set_cached_response(
    organization_id: UUID,
    endpoint: str,
    cache_key: str,
    payload: dict[str, Any],
    *,
    historical: bool = False,
    version: Optional[str] = None,
) -> None:
    """Cache a usage read. Empty ranges use a short TTL; closed history uses a longer one.

    ``version`` is the epoch read before the database query. A flush bumps that
    epoch while the query is running; the stale result is then discarded instead
    of being stored under the new epoch.
    """
    ttl = ttl_for_payload(
        historical=historical,
        empty=_is_empty_usage_payload(endpoint, payload),
    )
    if ttl <= 0:
        return
    expected = version if version is not None else _read_version(organization_id)
    try:
        client = _client()
        if _read_version(organization_id) != expected:
            return
        encoded = json.dumps(payload, default=str)
        client.set(
            _redis_key(organization_id, endpoint, cache_key, expected),
            encoded,
            ex=ttl,
        )
        if _read_version(organization_id) != expected:
            return
        client.set(
            _stale_key(organization_id, endpoint, cache_key),
            encoded,
            ex=ttl + _STALE_TTL_SECONDS,
        )
    except redis.RedisError as exc:
        logger.debug("usage read cache set failed org={}: {}", organization_id, exc)


def invalidate_org_usage_read_cache(organization_id: UUID) -> int:
    """Bump the org read epoch. Old keys expire on their own TTL."""
    try:
        client = _client()
        pipe = client.pipeline()
        pipe.incr(_version_key(organization_id))
        pipe.expire(_version_key(organization_id), _VERSION_TTL_SECONDS)
        pipe.execute()
        return 1
    except redis.RedisError as exc:
        logger.warning("usage read cache invalidate failed org={}: {}", organization_id, exc)
        return 0


def _load_json(raw: Optional[str]) -> Optional[dict[str, Any]]:
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def acquire_read_lock(organization_id: UUID, endpoint: str, cache_key: str) -> bool:
    try:
        return bool(
            _client().set(
                _lock_key(organization_id, endpoint, cache_key),
                "1",
                nx=True,
                ex=_LOCK_TTL_SECONDS,
            )
        )
    except redis.RedisError:
        return True


def release_read_lock(organization_id: UUID, endpoint: str, cache_key: str) -> None:
    try:
        _client().delete(_lock_key(organization_id, endpoint, cache_key))
    except redis.RedisError:
        pass


def get_stale_response(
    organization_id: UUID,
    endpoint: str,
    cache_key: str,
) -> Optional[dict[str, Any]]:
    try:
        return _load_json(_client().get(_stale_key(organization_id, endpoint, cache_key)))
    except redis.RedisError:
        return None


def wait_for_cached_response(
    organization_id: UUID,
    endpoint: str,
    cache_key: str,
    *,
    timeout_seconds: float = _FOLLOWER_WAIT_SECONDS,
) -> Optional[dict[str, Any]]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        time.sleep(0.05)
        cached = get_cached_response(organization_id, endpoint, cache_key)
        if cached is not None:
            return cached
    return None


def get_or_compute_cached_response(
    organization_id: UUID,
    endpoint: str,
    cache_key: str,
    compute_fn: Callable[[], dict[str, Any]],
    *,
    historical: bool = False,
) -> dict[str, Any]:
    """One database read per cache miss. Followers reuse the leader result or the last payload."""
    if cache_ttl_seconds() <= 0:
        return compute_fn()
    version = read_cache_version(organization_id)
    cached = get_cached_response(organization_id, endpoint, cache_key, version)
    if cached is not None:
        return cached
    leader = acquire_read_lock(organization_id, endpoint, cache_key)
    if not leader:
        stale = get_stale_response(organization_id, endpoint, cache_key)
        if stale is not None:
            return stale
        waited = wait_for_cached_response(organization_id, endpoint, cache_key)
        if waited is not None:
            return waited
        return compute_fn()
    try:
        payload = compute_fn()
        set_cached_response(
            organization_id,
            endpoint,
            cache_key,
            payload,
            historical=historical,
            version=version,
        )
        return payload
    finally:
        release_read_lock(organization_id, endpoint, cache_key)
