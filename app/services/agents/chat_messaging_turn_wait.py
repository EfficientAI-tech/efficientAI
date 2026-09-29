"""Redis-backed wait for Twilio SMS inbound replies during chat eval turns."""

from __future__ import annotations

import uuid
from typing import Optional

import redis
from loguru import logger

from app.config import settings

_redis_client: redis.Redis | None = None
_DEFAULT_TTL_SECS = 90


def _redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def _normalize_phone(value: str) -> str:
    return "".join(ch for ch in (value or "").strip() if ch.isdigit() or ch == "+")


def _pending_key(twilio_to: str, reply_from: str) -> str:
    return f"chat:messaging:pending:{_normalize_phone(twilio_to)}:{_normalize_phone(reply_from)}"


def _reply_list_key(turn_id: str) -> str:
    return f"chat:messaging:reply:{turn_id}"


def register_twilio_sms_turn(
    *,
    twilio_from: str,
    messaging_recipient: str,
    ttl_secs: int = _DEFAULT_TTL_SECS,
) -> str:
    """Register expectation: inbound SMS From recipient To twilio_from."""
    turn_id = str(uuid.uuid4())
    key = _pending_key(twilio_from, messaging_recipient)
    try:
        client = _redis()
        client.set(key, turn_id, ex=ttl_secs)
        client.delete(_reply_list_key(turn_id))
    except redis.RedisError as exc:
        logger.warning("[MessagingTurnWait] register failed: {}", exc)
    return turn_id


def wait_twilio_sms_reply(
    turn_id: str,
    *,
    timeout_secs: float = _DEFAULT_TTL_SECS,
) -> Optional[str]:
    if not turn_id:
        return None
    list_key = _reply_list_key(turn_id)
    try:
        result = _redis().blpop(list_key, timeout=max(1, int(timeout_secs)))
        if result and len(result) >= 2:
            body = (result[1] or "").strip()
            return body or None
    except redis.RedisError as exc:
        logger.warning("[MessagingTurnWait] wait failed: {}", exc)
    return None


def complete_twilio_sms_turn(
    *,
    twilio_to: str,
    reply_from: str,
    body: str,
    ttl_secs: int = _DEFAULT_TTL_SECS,
) -> bool:
    key = _pending_key(twilio_to, reply_from)
    try:
        client = _redis()
        turn_id = client.get(key)
        if not turn_id:
            return False
        client.delete(key)
        client.rpush(_reply_list_key(turn_id), (body or "").strip())
        client.expire(_reply_list_key(turn_id), ttl_secs)
        return True
    except redis.RedisError as exc:
        logger.warning("[MessagingTurnWait] complete failed: {}", exc)
        return False
