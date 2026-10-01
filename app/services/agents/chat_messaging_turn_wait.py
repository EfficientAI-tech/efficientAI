"""Redis-backed wait for Twilio SMS inbound replies during chat eval turns."""

from __future__ import annotations

import uuid
from typing import Optional
from uuid import UUID

import redis
from loguru import logger

from app.config import settings

_redis_client: redis.Redis | None = None
_DEFAULT_TTL_SECS = 90


def _redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        # BLPOP blocks longer than default socket read timeouts; keep socket open.
        _redis_client = redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=10,
            socket_timeout=None,
        )
    return _redis_client


def _normalize_phone(value: str) -> str:
    return "".join(ch for ch in (value or "").strip() if ch.isdigit() or ch == "+")


def _agent_token(agent_id: UUID | str) -> str:
    return str(agent_id).strip()


def _pending_key(agent_id: UUID | str, twilio_to: str, reply_from: str) -> str:
    return (
        f"chat:messaging:pending:{_agent_token(agent_id)}:"
        f"{_normalize_phone(twilio_to)}:{_normalize_phone(reply_from)}"
    )


def _pending_from_key(agent_id: UUID | str, reply_from: str) -> str:
    """Fallback when Twilio To differs from configured From (trial IDs); scoped to one agent."""
    return f"chat:messaging:pending:from:{_agent_token(agent_id)}:{_normalize_phone(reply_from)}"


def _reply_list_key(turn_id: str) -> str:
    return f"chat:messaging:reply:{turn_id}"


def register_twilio_sms_turn(
    *,
    agent_id: UUID | str,
    twilio_from: str,
    messaging_recipient: str,
    ttl_secs: int = _DEFAULT_TTL_SECS,
) -> str:
    """Register expectation: inbound SMS From recipient To twilio_from for this agent."""
    turn_id = str(uuid.uuid4())
    key = _pending_key(agent_id, twilio_from, messaging_recipient)
    from_key = _pending_from_key(agent_id, messaging_recipient)
    try:
        client = _redis()
        if not client.set(key, turn_id, ex=ttl_secs, nx=True):
            logger.warning(
                "[MessagingTurnWait] concurrent SMS eval for same From/To pair ({} -> {})",
                _normalize_phone(twilio_from),
                _normalize_phone(messaging_recipient),
            )
            return ""
        client.set(from_key, turn_id, ex=ttl_secs)
        client.delete(_reply_list_key(turn_id))
        logger.info(
            "[MessagingTurnWait] registered turn {} pending inbound from {} to {}",
            turn_id,
            _normalize_phone(messaging_recipient),
            _normalize_phone(twilio_from),
        )
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
    except redis.TimeoutError as exc:
        logger.warning("[MessagingTurnWait] wait timed out (no inbound SMS): {}", exc)
    return None


def complete_twilio_sms_turn(
    *,
    agent_id: UUID | str,
    twilio_to: str,
    reply_from: str,
    body: str,
    ttl_secs: int = _DEFAULT_TTL_SECS,
) -> bool:
    pair_key = _pending_key(agent_id, twilio_to, reply_from)
    from_key = _pending_from_key(agent_id, reply_from)
    try:
        client = _redis()
        turn_id = client.get(pair_key)
        matched_key = pair_key if turn_id else None
        if not turn_id:
            turn_id = client.get(from_key)
            matched_key = from_key if turn_id else None
        if not turn_id:
            logger.warning(
                "[MessagingTurnWait] no pending turn for inbound SMS "
                "(pair_key={}, from_key={}, from={}, to={})",
                pair_key,
                from_key,
                _normalize_phone(reply_from),
                _normalize_phone(twilio_to),
            )
            return False
        client.delete(pair_key)
        client.delete(from_key)
        client.rpush(_reply_list_key(turn_id), (body or "").strip())
        client.expire(_reply_list_key(turn_id), ttl_secs)
        logger.info(
            "[MessagingTurnWait] completed turn {} via key {}",
            turn_id,
            matched_key,
        )
        return True
    except redis.RedisError as exc:
        logger.warning("[MessagingTurnWait] complete failed: {}", exc)
        return False
