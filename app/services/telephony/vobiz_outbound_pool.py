"""Shared Vobiz outbound pool selection and per-org concurrency limits."""

from __future__ import annotations

import json
import logging
import time
from typing import List, Optional
from uuid import UUID

import redis
from sqlalchemy.orm import Session

from app.config import settings
from app.models.database import TelephonyPhoneNumber
from app.services.telephony.plivo_client import normalize_e164

logger = logging.getLogger(__name__)

_POOL_COUNTER_PREFIX = "vobiz:outbound_pool:org:"
_DEFAULT_TTL_SECONDS = 7200

_redis_client: redis.Redis | None = None
_in_memory_counters: dict[str, tuple[int, float]] = {}


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def _purge_expired_in_memory() -> None:
    now = time.time()
    expired = [key for key, (_, exp) in _in_memory_counters.items() if exp <= now]
    for key in expired:
        _in_memory_counters.pop(key, None)


def configured_outbound_pool() -> List[str]:
    """Return normalized platform outbound pool numbers."""
    raw = list(settings.VOBIZ_OUTBOUND_POOL or [])
    if settings.VOBIZ_FROM_NUMBER:
        raw.append(settings.VOBIZ_FROM_NUMBER)
    normalized: List[str] = []
    seen: set[str] = set()
    for value in raw:
        if not value:
            continue
        try:
            e164 = normalize_e164(value)
        except ValueError:
            continue
        if e164 not in seen:
            seen.add(e164)
            normalized.append(e164)
    return normalized


def _org_pool_key(org_id: UUID) -> str:
    return f"{_POOL_COUNTER_PREFIX}{org_id}"


def get_org_pool_usage(org_id: UUID) -> int:
    key = _org_pool_key(org_id)
    try:
        raw = _get_redis().get(key)
        if raw is None:
            return 0
        data = json.loads(raw)
        return int(data.get("count", 0))
    except redis.RedisError as exc:
        logger.warning("Redis unavailable for outbound pool usage: %s", exc)
        _purge_expired_in_memory()
        entry = _in_memory_counters.get(key)
        return entry[0] if entry and entry[1] > time.time() else 0
    except (json.JSONDecodeError, TypeError, ValueError):
        return 0


def acquire_pool_slot(org_id: UUID) -> bool:
    """Increment per-org concurrent pool usage if under the configured cap."""
    max_concurrent = max(int(settings.VOBIZ_OUTBOUND_POOL_MAX_CONCURRENT_PER_ORG or 5), 1)
    key = _org_pool_key(org_id)
    ttl = _DEFAULT_TTL_SECONDS
    try:
        pipe = _get_redis().pipeline()
        while True:
            current = get_org_pool_usage(org_id)
            if current >= max_concurrent:
                return False
            new_count = current + 1
            pipe.setex(key, ttl, json.dumps({"count": new_count}))
            pipe.execute()
            return True
    except redis.RedisError as exc:
        logger.warning("Redis unavailable for outbound pool acquire: %s", exc)
        _purge_expired_in_memory()
        entry = _in_memory_counters.get(key)
        current = entry[0] if entry and entry[1] > time.time() else 0
        if current >= max_concurrent:
            return False
        _in_memory_counters[key] = (current + 1, time.time() + ttl)
        return True


def release_pool_slot(org_id: UUID) -> None:
    """Decrement per-org concurrent pool usage after a call ends."""
    key = _org_pool_key(org_id)
    ttl = _DEFAULT_TTL_SECONDS
    try:
        current = get_org_pool_usage(org_id)
        new_count = max(current - 1, 0)
        if new_count == 0:
            _get_redis().delete(key)
        else:
            _get_redis().setex(key, ttl, json.dumps({"count": new_count}))
    except redis.RedisError as exc:
        logger.warning("Redis unavailable for outbound pool release: %s", exc)
        _purge_expired_in_memory()
        entry = _in_memory_counters.get(key)
        if not entry or entry[1] <= time.time():
            return
        new_count = max(entry[0] - 1, 0)
        if new_count == 0:
            _in_memory_counters.pop(key, None)
        else:
            _in_memory_counters[key] = (new_count, entry[1])


def resolve_outbound_from_number(
    db: Session,
    org_id: UUID,
    *,
    explicit_from_number: Optional[str] = None,
) -> tuple[str, bool]:
    """Choose caller-ID: explicit -> org imported outbound -> platform pool.

    Returns ``(from_number, used_pool)``.
    """
    if explicit_from_number:
        e164 = normalize_e164(explicit_from_number)
        owned = (
            db.query(TelephonyPhoneNumber)
            .filter(
                TelephonyPhoneNumber.organization_id == org_id,
                TelephonyPhoneNumber.phone_number == e164,
                TelephonyPhoneNumber.is_active.is_(True),
                TelephonyPhoneNumber.outbound_enabled.is_(True),
            )
            .first()
        )
        pool = configured_outbound_pool()
        if owned or e164 in pool:
            return e164, e164 in pool and not owned
        raise ValueError("from_number is not registered to this organization or outbound pool")

    org_number = (
        db.query(TelephonyPhoneNumber)
        .filter(
            TelephonyPhoneNumber.organization_id == org_id,
            TelephonyPhoneNumber.is_active.is_(True),
            TelephonyPhoneNumber.outbound_enabled.is_(True),
            TelephonyPhoneNumber.source != "platform_pool",
        )
        .order_by(TelephonyPhoneNumber.created_at.asc())
        .first()
    )
    if org_number:
        return org_number.phone_number, False

    pool = configured_outbound_pool()
    if not pool:
        raise ValueError(
            "No outbound caller ID available. Import a Vobiz number or configure VOBIZ_OUTBOUND_POOL."
        )
    if not acquire_pool_slot(org_id):
        raise ValueError("Outbound pool concurrency limit reached for this organization")
    return pool[0], True
