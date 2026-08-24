"""Shared platform outbound pool (multi-provider caller-ID fallback)."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, List, Optional, Set
from uuid import UUID

import redis
from sqlalchemy.orm import Session

from app.config import settings
from app.models.database import TelephonyPhoneNumber
from app.services.telephony.plivo_client import normalize_e164

logger = logging.getLogger(__name__)

_POOL_COUNTER_PREFIX = "telephony:outbound_pool:org:"
_DEFAULT_TTL_SECONDS = 7200
_SUPPORTED_POOL_PROVIDERS = frozenset({"vobiz", "plivo", "exotel", "twilio"})

_redis_client: redis.Redis | None = None
_in_memory_counters: dict[str, tuple[int, float]] = {}


@dataclass(frozen=True)
class PlatformOutboundPoolEntry:
    phone_number: str
    provider: str = "vobiz"


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


def _normalize_provider(provider: Optional[str], *, default: str = "vobiz") -> str:
    value = (provider or default).strip().lower()
    return value if value in _SUPPORTED_POOL_PROVIDERS else default


def _add_pool_entry(
    entries: List[PlatformOutboundPoolEntry],
    seen: Set[str],
    raw_number: Any,
    provider: str,
) -> None:
    if raw_number is None:
        return
    text = str(raw_number).strip()
    if not text:
        return
    try:
        e164 = normalize_e164(text)
    except ValueError:
        return
    if e164 in seen:
        return
    seen.add(e164)
    provider_key = _normalize_provider(provider)
    entries.append(PlatformOutboundPoolEntry(phone_number=e164, provider=provider_key))


def _parse_pool_items(
    items: List[Any],
    *,
    default_provider: str,
    entries: List[PlatformOutboundPoolEntry],
    seen: Set[str],
) -> None:
    for item in items:
        if isinstance(item, dict):
            number = item.get("number") or item.get("phone_number") or item.get("e164")
            provider = item.get("provider") or default_provider
            _add_pool_entry(entries, seen, number, provider)
        else:
            _add_pool_entry(entries, seen, item, default_provider)


def configured_outbound_pool() -> List[PlatformOutboundPoolEntry]:
    """Return normalized platform outbound pool entries across providers."""
    entries: List[PlatformOutboundPoolEntry] = []
    seen: set[str] = set()

    _parse_pool_items(
        list(settings.TELEPHONY_OUTBOUND_POOL or []),
        default_provider="vobiz",
        entries=entries,
        seen=seen,
    )
    _parse_pool_items(
        list(settings.VOBIZ_OUTBOUND_POOL or []),
        default_provider="vobiz",
        entries=entries,
        seen=seen,
    )
    if settings.VOBIZ_FROM_NUMBER:
        _add_pool_entry(entries, seen, settings.VOBIZ_FROM_NUMBER, "vobiz")

    _parse_pool_items(
        list(settings.PLIVO_OUTBOUND_POOL or []),
        default_provider="plivo",
        entries=entries,
        seen=seen,
    )
    _parse_pool_items(
        list(settings.EXOTEL_OUTBOUND_POOL or []),
        default_provider="exotel",
        entries=entries,
        seen=seen,
    )

    return entries


def configured_outbound_pool_numbers() -> List[str]:
    """Backward-compatible list of pool phone numbers (no provider metadata)."""
    return [entry.phone_number for entry in configured_outbound_pool()]


def pool_max_concurrent_per_org() -> int:
    value = (
        settings.TELEPHONY_OUTBOUND_POOL_MAX_CONCURRENT_PER_ORG
        if settings.TELEPHONY_OUTBOUND_POOL_MAX_CONCURRENT_PER_ORG is not None
        else settings.VOBIZ_OUTBOUND_POOL_MAX_CONCURRENT_PER_ORG
    )
    return max(int(value or 5), 1)


def outbound_pool_api_payload() -> dict[str, Any]:
    entries = configured_outbound_pool()
    return {
        "numbers": [
            {"phone_number": entry.phone_number, "provider": entry.provider}
            for entry in entries
        ],
        "max_concurrent_per_org": pool_max_concurrent_per_org(),
        "shared_across_orgs": True,
    }


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
    max_concurrent = pool_max_concurrent_per_org()
    key = _org_pool_key(org_id)
    ttl = _DEFAULT_TTL_SECONDS
    try:
        pipe = _get_redis().pipeline()
        while True:
            current = get_org_pool_usage(org_id)
            if current >= max_concurrent:
                return False
            new_count = current + 1
            pipe.set(key, json.dumps({"count": new_count}), ex=ttl)
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
            _get_redis().set(key, json.dumps({"count": new_count}), ex=ttl)
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


def _pool_entry_for_number(e164: str) -> Optional[PlatformOutboundPoolEntry]:
    for entry in configured_outbound_pool():
        if entry.phone_number == e164:
            return entry
    return None


def resolve_outbound_from_number(
    db: Session,
    org_id: UUID,
    *,
    explicit_from_number: Optional[str] = None,
) -> tuple[str, bool, str]:
    """Choose caller-ID: explicit -> org imported outbound -> platform pool.

    Returns ``(from_number, used_pool, provider)``.
    """
    pool_entries = configured_outbound_pool()
    pool_numbers = {entry.phone_number for entry in pool_entries}

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
        pool_entry = _pool_entry_for_number(e164)
        if owned:
            provider = "vobiz"
            if owned.telephony_integration_id:
                from app.models.database import TelephonyIntegration

                integration = (
                    db.query(TelephonyIntegration)
                    .filter(TelephonyIntegration.id == owned.telephony_integration_id)
                    .first()
                )
                if integration and integration.provider:
                    provider = integration.provider.lower()
            return e164, False, provider
        if pool_entry:
            return e164, True, pool_entry.provider
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
        provider = "vobiz"
        if org_number.telephony_integration_id:
            from app.models.database import TelephonyIntegration

            integration = (
                db.query(TelephonyIntegration)
                .filter(TelephonyIntegration.id == org_number.telephony_integration_id)
                .first()
            )
            if integration and integration.provider:
                provider = integration.provider.lower()
        return org_number.phone_number, False, provider

    if not pool_entries:
        raise ValueError(
            "No outbound caller ID available. Import an org number or configure "
            "telephony.outbound_pool in platform config."
        )
    if not acquire_pool_slot(org_id):
        raise ValueError("Outbound pool concurrency limit reached for this organization")

    first = pool_entries[0]
    return first.phone_number, True, first.provider
