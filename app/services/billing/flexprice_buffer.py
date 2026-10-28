"""Redis queue for deferred Flexprice ingest (flushed by the usage worker)."""

from __future__ import annotations

import json
from typing import Any, Optional, Union
from uuid import UUID

import redis
from loguru import logger

from app.config import settings

_QUEUE_KEY = "flexprice:pending:events"
_DEFAULT_FLUSH_BATCH = 100
_REQUEUE_TAIL = "flexprice:pending:requeue"

_redis: redis.Redis | None = None


def _client() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


def pending_event_count() -> int:
    try:
        return int(_client().llen(_QUEUE_KEY))
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
    from app.services.billing.flexprice_service import disabled_reason, record_event

    if disabled_reason():
        return {"flushed": 0, "failed": 0, "pending": pending_event_count()}

    client = _client()
    flushed = 0
    failed = 0
    limit = max(1, int(max_events))

    for _ in range(limit):
        raw = client.lpop(_QUEUE_KEY)
        if not raw:
            break
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

        if ok:
            flushed += 1
            continue

        failed += 1
        try:
            client.rpush(_REQUEUE_TAIL, raw)
        except redis.RedisError:
            pass

    if failed:
        try:
            while True:
                moved = client.rpoplpush(_REQUEUE_TAIL, _QUEUE_KEY)
                if not moved:
                    break
        except redis.RedisError as exc:
            logger.warning("Flexprice buffer requeue restore failed: {}", exc)

    return {"flushed": flushed, "failed": failed, "pending": pending_event_count()}
