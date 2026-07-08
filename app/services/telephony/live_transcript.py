"""Redis pub/sub helpers for streaming live call transcript turns to the UI."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

import redis

from app.config import settings

_redis_client: Optional[redis.Redis] = None


def _channel(call_short_id: str) -> str:
    return f"call:live:{call_short_id}"


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def publish_transcript_turn(call_short_id: str, role: str, content: str) -> None:
    if not call_short_id or not content.strip():
        return
    payload = {
        "role": role,
        "content": content.strip(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        _get_redis().publish(_channel(call_short_id), json.dumps(payload))
    except redis.RedisError:
        pass


async def subscribe_transcript_events(call_short_id: str) -> AsyncIterator[dict]:
    """Async generator yielding transcript turn dicts from Redis pub/sub."""
    client = _get_redis()
    pubsub = client.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(_channel(call_short_id))
    try:
        while True:
            message = pubsub.get_message(timeout=1.0)
            if not message:
                continue
            if message.get("type") != "message":
                continue
            data = message.get("data")
            if not data:
                continue
            try:
                yield json.loads(data)
            except json.JSONDecodeError:
                continue
    finally:
        try:
            pubsub.unsubscribe(_channel(call_short_id))
            pubsub.close()
        except Exception:
            pass
