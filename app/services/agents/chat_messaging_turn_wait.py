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
    return "".join(ch for ch in (value or "").strip() if ch.isdigit())


def _phone_lookup_variants(value: str) -> list[str]:
    """E.164 vs national formats — India 91 prefix only (no generic 10-digit tail)."""
    digits = _normalize_phone(value)
    if not digits:
        return []
    variants: list[str] = [digits]
    if digits.startswith("91") and len(digits) > 10:
        national = digits[2:]
        if national not in variants:
            variants.append(national)
    elif len(digits) == 10:
        intl = f"91{digits}"
        if intl not in variants:
            variants.append(intl)
    return variants


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


def _route_key(line: str, from_digits: str) -> str:
    """Maps inbound (business line, sender) to agent_id:turn_id for webhook routing."""
    return f"chat:messaging:route:{_normalize_phone(line)}:{_normalize_phone(from_digits)}"


def _redis_value_matches_turn(value: str | None, turn_id: str) -> bool:
    if not value or not turn_id:
        return False
    if value == turn_id:
        return True
    return value.endswith(f":{turn_id}") and ":" in value


def abandon_messaging_sms_turn(
    *,
    agent_id: UUID | str,
    twilio_from: str,
    messaging_recipient: str,
    turn_id: str,
) -> None:
    """Clear pending keys only when they still belong to this turn (avoids clobbering overlapping runs)."""
    if not turn_id:
        return
    try:
        client = _redis()
        from_variants = _phone_lookup_variants(messaging_recipient) or [
            _normalize_phone(messaging_recipient)
        ]
        line_variants = _phone_lookup_variants(twilio_from) or [_normalize_phone(twilio_from)]
        for fv in from_variants:
            for lv in line_variants:
                pair_key = _pending_key(agent_id, lv, fv)
                if _redis_value_matches_turn(client.get(pair_key), turn_id):
                    client.delete(pair_key)
                route_key = _route_key(lv, fv)
                if _redis_value_matches_turn(client.get(route_key), turn_id):
                    client.delete(route_key)
            from_key = _pending_from_key(agent_id, fv)
            if _redis_value_matches_turn(client.get(from_key), turn_id):
                client.delete(from_key)
    except redis.RedisError as exc:
        logger.warning("[MessagingTurnWait] abandon failed: {}", exc)


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
    try:
        client = _redis()
        from_variants = _phone_lookup_variants(messaging_recipient) or [
            _normalize_phone(messaging_recipient)
        ]
        line_variants = _phone_lookup_variants(twilio_from) or [_normalize_phone(twilio_from)]
        route_val = f"{_agent_token(agent_id)}:{turn_id}"
        claimed_routes: list[str] = []
        for fv in from_variants:
            for lv in line_variants:
                route_key = _route_key(lv, fv)
                if client.set(route_key, route_val, ex=ttl_secs, nx=True):
                    claimed_routes.append(route_key)
                    continue
                if client.get(route_key) == route_val:
                    claimed_routes.append(route_key)
                    continue
                for claimed in claimed_routes:
                    if client.get(claimed) == route_val:
                        client.delete(claimed)
                logger.warning(
                    "[MessagingTurnWait] line already waiting for another run ({} -> {})",
                    _normalize_phone(twilio_from),
                    _normalize_phone(messaging_recipient),
                )
                return ""
        if not client.set(key, turn_id, ex=ttl_secs, nx=True):
            for claimed in claimed_routes:
                if client.get(claimed) == route_val:
                    client.delete(claimed)
            logger.warning(
                "[MessagingTurnWait] concurrent SMS eval for same From/To pair ({} -> {})",
                _normalize_phone(twilio_from),
                _normalize_phone(messaging_recipient),
            )
            return ""
        for recipient_variant in from_variants:
            client.set(_pending_from_key(agent_id, recipient_variant), turn_id, ex=ttl_secs)
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
        return None
    except redis.TimeoutError as exc:
        logger.warning("[MessagingTurnWait] wait timed out (no inbound SMS): {}", exc)
    return None


def wait_messaging_sms_reply_or_raise(
    turn_id: str,
    *,
    timeout_secs: float = _DEFAULT_TTL_SECS,
) -> Optional[str]:
    """Wait for inbound reply; distinguish Redis outage from empty timeout."""
    if not turn_id:
        return None
    list_key = _reply_list_key(turn_id)
    try:
        client = _redis()
        client.ping()
    except redis.RedisError as exc:
        raise RuntimeError(f"Redis unavailable for messaging turn wait: {exc}") from exc
    return wait_messaging_sms_reply(turn_id, timeout_secs=timeout_secs)


def complete_messaging_sms_turn(
    *,
    agent_id: UUID | str,
    line_to: str,
    reply_from: str,
    body: str,
    ttl_secs: int = _DEFAULT_TTL_SECS,
) -> bool:
    try:
        client = _redis()
        turn_id = None
        matched_key = None
        line_variants = _phone_lookup_variants(line_to) or [_normalize_phone(line_to)]
        from_variants = _phone_lookup_variants(reply_from) or [_normalize_phone(reply_from)]
        for fv in from_variants:
            for lv in line_variants:
                pair_key = _pending_key(agent_id, lv, fv)
                turn_id = client.get(pair_key)
                if turn_id:
                    matched_key = pair_key
                    break
            if turn_id:
                break
        if not turn_id:
            for fv in from_variants:
                from_key = _pending_from_key(agent_id, fv)
                turn_id = client.get(from_key)
                if turn_id:
                    matched_key = from_key
                    break
        if not turn_id:
            logger.warning(
                "[MessagingTurnWait] no pending turn for inbound SMS "
                "(from={}, to={}, from_variants={}, line_variants={})",
                _normalize_phone(reply_from),
                _normalize_phone(line_to),
                from_variants,
                line_variants,
            )
            return False
        for fv in from_variants:
            for lv in line_variants:
                pair_key = _pending_key(agent_id, lv, fv)
                if _redis_value_matches_turn(client.get(pair_key), turn_id):
                    client.delete(pair_key)
                route_key = _route_key(lv, fv)
                if _redis_value_matches_turn(client.get(route_key), turn_id):
                    client.delete(route_key)
            from_key = _pending_from_key(agent_id, fv)
            if _redis_value_matches_turn(client.get(from_key), turn_id):
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


def complete_messaging_inbound_routed(
    *,
    line_to: str,
    reply_from: str,
    body: str,
    ttl_secs: int = _DEFAULT_TTL_SECS,
    expected_agent_id: str | None = None,
) -> bool:
    """Complete a pending turn using Redis route keys (no DB agent lookup)."""
    try:
        client = _redis()
        line_variants = _phone_lookup_variants(line_to) or [_normalize_phone(line_to)]
        from_variants = _phone_lookup_variants(reply_from) or [_normalize_phone(reply_from)]
        for fv in from_variants:
            for lv in line_variants:
                route_val = client.get(_route_key(lv, fv))
                if not route_val:
                    continue
                parts = str(route_val).split(":", 1)
                if len(parts) != 2:
                    continue
                agent_id, _turn_id = parts[0], parts[1]
                if expected_agent_id and str(agent_id) != str(expected_agent_id):
                    continue
                return complete_messaging_sms_turn(
                    agent_id=agent_id,
                    line_to=line_to,
                    reply_from=reply_from,
                    body=body,
                    ttl_secs=ttl_secs,
                )
    except redis.RedisError as exc:
        logger.warning("[MessagingTurnWait] routed complete failed: {}", exc)
    return False


def complete_twilio_sms_turn(
    *,
    agent_id: UUID | str,
    twilio_to: str,
    reply_from: str,
    body: str,
    ttl_secs: int = _DEFAULT_TTL_SECS,
) -> bool:
    return complete_messaging_sms_turn(
        agent_id=agent_id,
        line_to=twilio_to,
        reply_from=reply_from,
        body=body,
        ttl_secs=ttl_secs,
    )


register_messaging_sms_turn = register_twilio_sms_turn
wait_messaging_sms_reply = wait_twilio_sms_reply
