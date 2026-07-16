"""Redis-backed per-credential rate limits for authenticated call-import fetches."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Optional

import redis
from loguru import logger

from app.config import settings
from app.core.encryption import decrypt_api_key

_redis_client: redis.Redis | None = None

_KEY_PREFIX = "telephony:import"


@dataclass(frozen=True)
class CreditStatus:
    allowed: bool
    wait_seconds: int = 0
    remaining: int = 0


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def _credits_key(fingerprint: str) -> str:
    return f"{_KEY_PREFIX}:credits:{fingerprint}"


def _window_key(fingerprint: str) -> str:
    return f"{_KEY_PREFIX}:window_start:{fingerprint}"


def _blocked_key(fingerprint: str) -> str:
    return f"{_KEY_PREFIX}:blocked_until:{fingerprint}"


def _backoff_level_key(fingerprint: str) -> str:
    return f"{_KEY_PREFIX}:backoff_level:{fingerprint}"


def _credit_limit() -> int:
    return max(1, int(settings.TELEPHONY_IMPORT_CREDIT_LIMIT))


def _window_seconds() -> int:
    return max(1, int(settings.TELEPHONY_IMPORT_CREDIT_WINDOW_SECONDS))


def _backoff_base_seconds() -> int:
    return max(1, int(settings.TELEPHONY_IMPORT_BACKOFF_BASE_SECONDS))


def _backoff_max_seconds() -> int:
    return max(_backoff_base_seconds(), int(settings.TELEPHONY_IMPORT_BACKOFF_MAX_SECONDS))


def telephony_credential_fingerprint(
    provider: str,
    auth_id: str,
    api_endpoint: str,
) -> str:
    """Stable fingerprint for a shared telephony credential."""
    provider_key = (provider or "").strip().lower()
    endpoint = (api_endpoint or "").strip().lower().rstrip("/")
    payload = f"{provider_key}:{auth_id}:{endpoint}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def api_endpoint_for_integration(integration) -> str:
    """Resolve the API endpoint used for provider rate-limit bucketing."""
    provider_key = (getattr(integration, "provider", None) or "").strip().lower()
    sip_domain = (getattr(integration, "sip_domain", None) or "").strip()
    if provider_key == "exotel":
        from app.services.telephony.exotel_client import resolve_exotel_api_base

        return resolve_exotel_api_base(sip_domain or None)
    if sip_domain:
        return sip_domain.rstrip("/").lower()
    return provider_key or "default"


def fingerprint_for_integration(integration) -> str:
    auth_id = decrypt_api_key(integration.auth_id)
    return telephony_credential_fingerprint(
        integration.provider,
        auth_id,
        api_endpoint_for_integration(integration),
    )


def requires_authenticated_recording_fetch(call_import) -> bool:
    """True when call-import recording fetch uses provider HTTP auth."""
    if call_import.telephony_integration_id is None and not (
        call_import.provider or ""
    ).strip():
        return False
    return (call_import.provider or "").strip().lower() == "exotel"


_PEEK_LUA = """
local credits_key = KEYS[1]
local window_key = KEYS[2]
local blocked_key = KEYS[3]
local limit = tonumber(ARGV[1])
local window_seconds = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

local blocked_until = tonumber(redis.call('GET', blocked_key) or '0')
if blocked_until > now then
  return {0, blocked_until - now, tonumber(redis.call('GET', credits_key) or limit)}
end

local window_start = tonumber(redis.call('GET', window_key) or '0')
local credits = tonumber(redis.call('GET', credits_key) or limit)
if window_start == 0 or (now - window_start) >= window_seconds then
  credits = limit
end

if credits > 0 then
  return {1, 0, credits}
end

local wait = window_seconds
if window_start > 0 then
  local window_end = window_start + window_seconds
  if window_end > now then
    wait = window_end - now
  end
end
return {0, wait, 0}
"""

_CONSUME_LUA = """
local credits_key = KEYS[1]
local window_key = KEYS[2]
local blocked_key = KEYS[3]
local backoff_key = KEYS[4]
local limit = tonumber(ARGV[1])
local window_seconds = tonumber(ARGV[2])
local base_backoff = tonumber(ARGV[3])
local max_backoff = tonumber(ARGV[4])
local now = tonumber(ARGV[5])

local blocked_until = tonumber(redis.call('GET', blocked_key) or '0')
if blocked_until > now then
  return {0, blocked_until - now, tonumber(redis.call('GET', credits_key) or '0')}
end

local window_start = tonumber(redis.call('GET', window_key) or '0')
local credits = tonumber(redis.call('GET', credits_key) or limit)
if window_start == 0 or (now - window_start) >= window_seconds then
  window_start = now
  credits = limit
  redis.call('SET', window_key, window_start)
  redis.call('SET', backoff_key, 0)
end

if credits > 0 then
  credits = credits - 1
  redis.call('SET', credits_key, credits)
  redis.call('EXPIRE', credits_key, window_seconds * 2)
  redis.call('EXPIRE', window_key, window_seconds * 2)
  return {1, 0, credits}
end

local level = tonumber(redis.call('GET', backoff_key) or '0') + 1
redis.call('SET', backoff_key, level)
local wait = math.min(max_backoff, base_backoff * (2 ^ (level - 1)))
local window_end = window_start + window_seconds
if window_end > now and (window_end - now) > wait then
  wait = window_end - now
end
blocked_until = now + wait
redis.call('SET', blocked_key, blocked_until)
redis.call('EXPIRE', blocked_key, wait + window_seconds)
return {0, wait, 0}
"""

_PENALIZE_LUA = """
local blocked_key = KEYS[1]
local backoff_key = KEYS[2]
local base_backoff = tonumber(ARGV[1])
local max_backoff = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local retry_after = tonumber(ARGV[4])

local level = tonumber(redis.call('GET', backoff_key) or '0') + 1
redis.call('SET', backoff_key, level)
local wait = retry_after
if wait <= 0 then
  wait = math.min(max_backoff, base_backoff * (2 ^ (level - 1)))
end
local blocked_until = now + wait
redis.call('SET', blocked_key, blocked_until)
redis.call('EXPIRE', blocked_key, wait + 60)
return wait
"""


def _now_seconds() -> int:
    return int(time.time())


def _status_from_result(result) -> CreditStatus:
    allowed = bool(int(result[0] or 0))
    wait_seconds = max(0, int(result[1] or 0))
    remaining = max(0, int(result[2] or 0))
    return CreditStatus(
        allowed=allowed,
        wait_seconds=wait_seconds,
        remaining=remaining,
    )


def peek_telephony_import_credit(fingerprint: str) -> CreditStatus:
    """Read whether a credential has budget without consuming a credit."""
    try:
        client = _get_redis()
        now = _now_seconds()
        result = client.eval(
            _PEEK_LUA,
            3,
            _credits_key(fingerprint),
            _window_key(fingerprint),
            _blocked_key(fingerprint),
            str(_credit_limit()),
            str(_window_seconds()),
            str(now),
        )
        return _status_from_result(result)
    except redis.RedisError as exc:
        logger.warning("Telephony credit peek failed (Redis error): {}", exc)
        return CreditStatus(allowed=True, remaining=_credit_limit())


def consume_telephony_import_credit(fingerprint: str) -> CreditStatus:
    """Atomically consume one import credit for a shared credential."""
    try:
        client = _get_redis()
        now = _now_seconds()
        result = client.eval(
            _CONSUME_LUA,
            4,
            _credits_key(fingerprint),
            _window_key(fingerprint),
            _blocked_key(fingerprint),
            _backoff_level_key(fingerprint),
            str(_credit_limit()),
            str(_window_seconds()),
            str(_backoff_base_seconds()),
            str(_backoff_max_seconds()),
            str(now),
        )
        return _status_from_result(result)
    except redis.RedisError as exc:
        logger.warning("Telephony credit consume failed (Redis error): {}", exc)
        return CreditStatus(allowed=True, remaining=_credit_limit())


def penalize_telephony_credential(
    fingerprint: str,
    *,
    retry_after_seconds: Optional[int] = None,
) -> int:
    """Block a credential after a throttle-suspect provider response."""
    try:
        client = _get_redis()
        now = _now_seconds()
        retry_after = max(0, int(retry_after_seconds or 0))
        wait = client.eval(
            _PENALIZE_LUA,
            2,
            _blocked_key(fingerprint),
            _backoff_level_key(fingerprint),
            str(_backoff_base_seconds()),
            str(_backoff_max_seconds()),
            str(now),
            str(retry_after),
        )
        return max(1, int(wait or _backoff_base_seconds()))
    except redis.RedisError as exc:
        logger.warning("Telephony credential penalize failed (Redis error): {}", exc)
        return _backoff_base_seconds()
