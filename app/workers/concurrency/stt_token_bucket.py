"""Per-provider token bucket for call-import speech-to-text (fail-closed)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import redis
from loguru import logger

from app.config import settings

_TOKEN_WINDOW_SECONDS = 60

_redis: redis.Redis | None = None

_TOKEN_LUA = """
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local rpm = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])
local member = ARGV[5]
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
local count = redis.call('ZCARD', KEYS[1])
if count + cost > rpm then
  return 0
end
for i = 1, cost do
  redis.call('ZADD', KEYS[1], now, member .. ':' .. i)
end
redis.call('EXPIRE', KEYS[1], math.floor(window * 2))
return 1
"""


@dataclass(frozen=True)
class SttTokenResult:
    allowed: bool
    wait_seconds: int = 0


def _client() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


def _token_key(provider: str) -> str:
    key = (provider or "").strip().lower() or "unknown"
    return f"call_import:stt:tokens:{key}"


def stt_rpm_for_provider(provider: str) -> int:
    normalized = (provider or "").strip().lower()
    table = getattr(settings, "CALL_IMPORT_STT_RPM_BY_PROVIDER", None) or {}
    if normalized in table:
        return max(1, int(table[normalized]))
    return max(1, int(settings.CALL_IMPORT_STT_RPM_DEFAULT))


def waiting_stt_message(provider: str) -> str:
    label = (provider or "provider").strip() or "provider"
    return f"Waiting for {label} speech-to-text capacity."


def consume_stt_token(
    provider: str,
    *,
    cost: int = 1,
    member: str | None = None,
) -> SttTokenResult:
    """Acquire one STT slot for ``provider``. Redis errors refuse the call."""
    rpm = stt_rpm_for_provider(provider)
    token_member = member or f"{time.time()}:{id(provider)}"
    try:
        allowed = _client().eval(
            _TOKEN_LUA,
            1,
            _token_key(provider),
            str(time.time()),
            str(_TOKEN_WINDOW_SECONDS),
            str(rpm),
            str(max(1, int(cost))),
            token_member,
        )
        if int(allowed or 0):
            return SttTokenResult(True)
        denied_wait = max(1, int(settings.TELEPHONY_IMPORT_BACKOFF_BASE_SECONDS))
        return SttTokenResult(False, wait_seconds=denied_wait)
    except redis.RedisError as exc:
        logger.warning("call-import STT token bucket failed: {}", exc)
        return SttTokenResult(False, wait_seconds=5)
