"""Redis queue for deferred Flexprice ingest (flushed by the usage worker)."""

from __future__ import annotations

import json
from typing import Any, Optional, Union
from uuid import UUID

import redis
from loguru import logger

from app.config import settings

_QUEUE_KEY = "flexprice:pending:events"
_INFLIGHT_KEY = "flexprice:pending:inflight"
_FLUSH_LOCK_KEY = "flexprice:pending:flush_lock"
_FLUSH_LOCK_SECONDS = 300
_DEFAULT_FLUSH_BATCH = 100

_redis: redis.Redis | None = None


def _client() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


def pending_event_count() -> int:
    try:
        client = _client()
        queued = int(client.llen(_QUEUE_KEY) or 0)
        inflight = int(client.llen(_INFLIGHT_KEY) or 0)
        return queued + inflight
    except redis.RedisError:
        return 0


def enqueue_flexprice_event(
    event_name: str,
    organization_id: UUID,
    event_id: Union[str, UUID],
    *,
    properties: Optional[dict[str, Any]] = None,
) -> bool:
    from app.services.billing.flexprice_service import disabled_reason

    if disabled_reason():
        return False

    payload = json.dumps(
        {
            "event_name": event_name,
            "organization_id": str(organization_id),
            "event_id": str(event_id),
            "properties": properties or {},
        },
        separators=(",", ":"),
        default=str,
    )
    try:
        client = _client()
        client.rpush(_QUEUE_KEY, payload)
        return True
    except redis.RedisError as exc:
        logger.warning(
            "Flexprice buffer enqueue failed org={} event={} error={}",
            organization_id,
            event_name,
            exc,
        )
        return False


def flush_buffered_flexprice_events(
    *,
    max_events: int = _DEFAULT_FLUSH_BATCH,
) -> dict[str, int]:
    """Send queued events. An item leaves Redis only after Flexprice accepts it.

    Claim moves the payload onto an inflight list (still in Redis). ``LREM``
    runs only after ``record_event`` returns true. A crash retries the same
    ``event_id`` on the next flush.
    """
    from app.services.billing.flexprice_service import disabled_reason, record_event

    if disabled_reason():
        return {"flushed": 0, "failed": 0, "pending": pending_event_count()}

    client = _client()
    try:
        locked = client.set(
            _FLUSH_LOCK_KEY,
            "1",
            nx=True,
            ex=_FLUSH_LOCK_SECONDS,
        )
    except redis.RedisError as exc:
        logger.warning("Flexprice flush lock failed: {}", exc)
        return {"flushed": 0, "failed": 0, "pending": pending_event_count()}
    if not locked:
        return {
            "flushed": 0,
            "failed": 0,
            "pending": pending_event_count(),
            "skipped_locked": 1,
        }

    flushed = 0
    failed = 0
    limit = max(1, int(max_events))
    attempted: set[str] = set()
    try:
        for _ in range(limit):
            try:
                raw = client.lindex(_INFLIGHT_KEY, 0)
                if not raw:
                    raw = client.lmove(
                        _QUEUE_KEY,
                        _INFLIGHT_KEY,
                        "LEFT",
                        "LEFT",
                    )
            except redis.RedisError as exc:
                logger.warning("Flexprice flush claim failed: {}", exc)
                failed += 1
                break
            if not raw:
                break
            if raw in attempted:
                break
            attempted.add(raw)
            try:
                item = json.loads(raw)
                ok = record_event(
                    item["event_name"],
                    UUID(item["organization_id"]),
                    item["event_id"],
                    properties=item.get("properties") or {},
                )
            except Exception as exc:
                logger.warning("Flexprice buffer flush parse/send failed: {}", exc)
                ok = False

            if not ok:
                failed += 1
                try:
                    client.lmove(_INFLIGHT_KEY, _QUEUE_KEY, "LEFT", "RIGHT")
                except redis.RedisError as exc:
                    logger.warning("Flexprice inflight rotate failed: {}", exc)
                    break
                continue

            try:
                client.lrem(_INFLIGHT_KEY, 1, raw)
            except redis.RedisError as exc:
                logger.warning(
                    "Flexprice inflight remove failed after ingest: {}",
                    exc,
                )
            flushed += 1
    finally:
        try:
            client.delete(_FLUSH_LOCK_KEY)
        except redis.RedisError as exc:
            logger.warning("Flexprice flush lock release failed: {}", exc)

    return {"flushed": flushed, "failed": failed, "pending": pending_event_count()}
