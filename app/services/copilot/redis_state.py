"""Redis-backed copilot guards and live turn state.

Everything here is best-effort: if Redis is unreachable we log and fail open.
The per-process turn cap (``turn_runner``) still bounds load, and the database
stays the source of truth for messages, so a Redis outage degrades limits and
resume-after-reconnect but never loses a conversation.

Keys (all expire on their own):
  copilot:rl:u:{user}:{minute}     per-user messages per minute
  copilot:rl:o:{org}:{minute}      per-org messages per minute
  copilot:tok:{org}:{yyyymmdd}     per-org LLM tokens today
  copilot:lock:{user}              the user's active turn (message id)
  copilot:cancel:{message}         cancel requested for a turn
  copilot:snap:{message}           live snapshot of a streaming reply
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

import redis
from loguru import logger

from app.config import settings

_redis: Optional[redis.Redis] = None

SNAPSHOT_TTL_SECONDS = 600
_TOKEN_KEY_TTL_SECONDS = 2 * 86400

# Delete the lock only if it still belongs to this turn (a timed-out turn must
# not release the lock a newer turn now holds).
_RELEASE_LOCK = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


def _client() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
    return _redis


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after_seconds: int = 0
    scope: Optional[str] = None


def check_message_rate(user_id: UUID, organization_id: UUID) -> RateLimitResult:
    """Fixed one-minute windows: two INCRs per message, cheap at any volume."""
    minute = int(time.time() // 60)
    retry_after = 60 - int(time.time() % 60)
    user_key = f"copilot:rl:u:{user_id}:{minute}"
    org_key = f"copilot:rl:o:{organization_id}:{minute}"
    try:
        pipe = _client().pipeline()
        pipe.incr(user_key)
        pipe.expire(user_key, 120)
        pipe.incr(org_key)
        pipe.expire(org_key, 120)
        user_count, _, org_count, _ = pipe.execute()
    except redis.RedisError as exc:
        logger.warning("[Copilot] rate limiter unavailable, allowing: {}", exc)
        return RateLimitResult(allowed=True)
    if int(user_count) > max(1, settings.COPILOT_USER_MESSAGES_PER_MINUTE):
        return RateLimitResult(False, retry_after, "user")
    if int(org_count) > max(1, settings.COPILOT_ORG_MESSAGES_PER_MINUTE):
        return RateLimitResult(False, retry_after, "organization")
    return RateLimitResult(allowed=True)


def _token_key(organization_id: UUID) -> str:
    return f"copilot:tok:{organization_id}:{datetime.now(timezone.utc):%Y%m%d}"


def org_token_budget_exhausted(organization_id: UUID) -> bool:
    budget = settings.COPILOT_ORG_DAILY_TOKEN_BUDGET
    if budget <= 0:
        return False
    try:
        used = _client().get(_token_key(organization_id))
    except redis.RedisError as exc:
        logger.warning("[Copilot] token budget unavailable, allowing: {}", exc)
        return False
    return int(used or 0) >= budget


def add_org_tokens(organization_id: UUID, tokens: int) -> None:
    if tokens <= 0:
        return
    key = _token_key(organization_id)
    try:
        pipe = _client().pipeline()
        pipe.incrby(key, int(tokens))
        pipe.expire(key, _TOKEN_KEY_TTL_SECONDS)
        pipe.execute()
    except redis.RedisError as exc:
        logger.warning("[Copilot] could not record tokens: {}", exc)


def acquire_turn_lock(user_id: UUID, message_id: UUID) -> bool:
    """One streaming turn per user. Returns False if another turn holds it."""
    ttl = settings.COPILOT_TURN_TIMEOUT_SECONDS + 30
    try:
        return bool(_client().set(f"copilot:lock:{user_id}", str(message_id), nx=True, ex=ttl))
    except redis.RedisError as exc:
        logger.warning("[Copilot] turn lock unavailable, allowing: {}", exc)
        return True


def release_turn_lock(user_id: UUID, message_id: UUID) -> None:
    try:
        _client().eval(_RELEASE_LOCK, 1, f"copilot:lock:{user_id}", str(message_id))
    except redis.RedisError as exc:
        logger.warning("[Copilot] could not release turn lock: {}", exc)


def request_cancel(message_id: UUID) -> None:
    try:
        _client().set(f"copilot:cancel:{message_id}", "1", ex=SNAPSHOT_TTL_SECONDS)
    except redis.RedisError as exc:
        logger.warning("[Copilot] could not record cancel: {}", exc)


def is_cancelled(message_id: UUID) -> bool:
    try:
        return bool(_client().exists(f"copilot:cancel:{message_id}"))
    except redis.RedisError:
        return False


def write_snapshot(message_id: UUID, snapshot: dict[str, Any]) -> None:
    try:
        _client().set(
            f"copilot:snap:{message_id}",
            json.dumps(snapshot, default=str),
            ex=SNAPSHOT_TTL_SECONDS,
        )
    except redis.RedisError as exc:
        logger.debug("[Copilot] snapshot write skipped: {}", exc)


def read_snapshots(message_ids: list[UUID]) -> dict[UUID, dict[str, Any]]:
    if not message_ids:
        return {}
    try:
        raw = _client().mget([f"copilot:snap:{mid}" for mid in message_ids])
    except redis.RedisError:
        return {}
    out: dict[UUID, dict[str, Any]] = {}
    for mid, value in zip(message_ids, raw):
        if value:
            try:
                out[mid] = json.loads(value)
            except ValueError:
                continue
    return out
