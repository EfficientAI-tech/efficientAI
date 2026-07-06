"""Short-lived Vobiz outbound call session mapping (call_ref -> agent/org)."""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Dict, Optional

import redis

from app.config import settings

logger = logging.getLogger(__name__)

_SESSION_PREFIX = "vobiz:call_session:"
_DEFAULT_TTL_SECONDS = 3600

_redis_client: redis.Redis | None = None
_in_memory_sessions: Dict[str, tuple[str, float]] = {}


@dataclass(frozen=True)
class VobizCallSession:
    call_ref: str
    agent_id: str
    organization_id: str
    direction: str = "outbound"
    from_number: Optional[str] = None
    to_number: Optional[str] = None
    used_pool: bool = False
    persona_id: Optional[str] = None
    scenario_id: Optional[str] = None
    evaluator_id: Optional[str] = None


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def _purge_expired_in_memory() -> None:
    now = time.time()
    expired = [key for key, (_, exp) in _in_memory_sessions.items() if exp <= now]
    for key in expired:
        _in_memory_sessions.pop(key, None)


def create_call_session(
    *,
    agent_id: str,
    organization_id: str,
    direction: str = "outbound",
    from_number: Optional[str] = None,
    to_number: Optional[str] = None,
    used_pool: bool = False,
    persona_id: Optional[str] = None,
    scenario_id: Optional[str] = None,
    evaluator_id: Optional[str] = None,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> VobizCallSession:
    """Create and persist a call session, returning its opaque call_ref."""
    call_ref = uuid.uuid4().hex
    payload = {
        "agent_id": str(agent_id),
        "organization_id": str(organization_id),
        "direction": direction,
        "from_number": from_number,
        "to_number": to_number,
        "used_pool": used_pool,
        "persona_id": persona_id,
        "scenario_id": scenario_id,
        "evaluator_id": evaluator_id,
    }
    ttl = max(int(ttl_seconds), 60)
    key = f"{_SESSION_PREFIX}{call_ref}"
    try:
        _get_redis().setex(key, ttl, json.dumps(payload))
    except redis.RedisError as exc:
        logger.warning("Redis unavailable for Vobiz session; using in-memory fallback: %s", exc)
        _purge_expired_in_memory()
        _in_memory_sessions[key] = (json.dumps(payload), time.time() + ttl)
    return VobizCallSession(
        call_ref=call_ref,
        agent_id=str(agent_id),
        organization_id=str(organization_id),
        direction=direction,
        from_number=from_number,
        to_number=to_number,
        used_pool=used_pool,
        persona_id=persona_id,
        scenario_id=scenario_id,
        evaluator_id=evaluator_id,
    )


def get_call_session(call_ref: str) -> Optional[VobizCallSession]:
    """Load a call session by opaque call_ref."""
    if not call_ref:
        return None
    key = f"{_SESSION_PREFIX}{call_ref}"
    raw: Optional[str] = None
    try:
        raw = _get_redis().get(key)
    except redis.RedisError as exc:
        logger.warning("Redis unavailable for Vobiz session lookup; using in-memory fallback: %s", exc)
        _purge_expired_in_memory()
        entry = _in_memory_sessions.get(key)
        if entry and entry[1] > time.time():
            raw = entry[0]
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return VobizCallSession(
        call_ref=call_ref,
        agent_id=data.get("agent_id", ""),
        organization_id=data.get("organization_id", ""),
        direction=data.get("direction", "outbound"),
        from_number=data.get("from_number"),
        to_number=data.get("to_number"),
        used_pool=bool(data.get("used_pool")),
        persona_id=data.get("persona_id"),
        scenario_id=data.get("scenario_id"),
        evaluator_id=data.get("evaluator_id"),
    )


def delete_call_session(call_ref: str) -> None:
    """Remove a call session after the call ends."""
    if not call_ref:
        return
    key = f"{_SESSION_PREFIX}{call_ref}"
    try:
        _get_redis().delete(key)
    except redis.RedisError as exc:
        logger.warning("Redis unavailable for Vobiz session delete; using in-memory fallback: %s", exc)
        _in_memory_sessions.pop(key, None)
