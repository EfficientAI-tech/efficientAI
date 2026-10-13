"""Rate limits and in-flight slots for platform historical imports."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

import redis
from loguru import logger

from app.config import settings

_PLATFORM_SLOT_TTL_SECONDS = 20 * 60
_redis: redis.Redis | None = None


def rpm_for_speed(speed: Optional[str]) -> int:
    key = (speed or "standard").strip().lower()
    table = {
        "gentle": int(settings.PLATFORM_IMPORT_RPM_GENTLE),
        "standard": int(settings.PLATFORM_IMPORT_RPM_STANDARD),
        "fast": int(settings.PLATFORM_IMPORT_RPM_FAST),
    }
    return table.get(key, table["standard"])


def _client() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


def _ws_key(workspace_id: UUID | str) -> str:
    return f"platform_import:ws:{workspace_id}"


def _org_key(organization_id: UUID | str) -> str:
    return f"platform_import:org:{organization_id}"


def _global_key() -> str:
    return "platform_import:global"


def _task_key(celery_task_id: str) -> str:
    return f"platform_import:task:{celery_task_id}"


def _token_key(integration_id: UUID | str) -> str:
    return f"platform_import:tokens:{integration_id}"


def _auth_fail_key(integration_id: UUID | str) -> str:
    return f"platform_import:auth_fail:{integration_id}"


@dataclass
class TokenResult:
    allowed: bool
    wait_seconds: int = 0


def _lease_ws_key(workspace_id: UUID | str) -> str:
    return f"platform_import:lease:ws:{workspace_id}"


def _lease_org_key(organization_id: UUID | str) -> str:
    return f"platform_import:lease:org:{organization_id}"


def _lease_global_key() -> str:
    return "platform_import:lease:global"


def _lease_import_key(call_import_id: UUID | str) -> str:
    return f"platform_import:lease:import:{call_import_id}"


def _lease_meta_key(celery_task_id: str) -> str:
    return f"platform_import:lease:meta:{celery_task_id}"


_ACQUIRE_LEASE_LUA = """
local now = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local ws_limit = tonumber(ARGV[3])
local org_limit = tonumber(ARGV[4])
local glob_limit = tonumber(ARGV[5])
local import_limit = tonumber(ARGV[6])
local task_id = ARGV[7]
local ws = ARGV[8]
local org = ARGV[9]
local import_id = ARGV[10]
local expiry = now + ttl
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now)
redis.call('ZREMRANGEBYSCORE', KEYS[3], '-inf', now)
if import_id ~= '' then
  redis.call('ZREMRANGEBYSCORE', KEYS[4], '-inf', now)
end
if redis.call('ZCARD', KEYS[1]) >= ws_limit then return 0 end
if redis.call('ZCARD', KEYS[2]) >= org_limit then return 0 end
if redis.call('ZCARD', KEYS[3]) >= glob_limit then return 0 end
if import_id ~= '' and import_limit > 0 and redis.call('ZCARD', KEYS[4]) >= import_limit then
  return 0
end
redis.call('ZADD', KEYS[1], expiry, task_id)
redis.call('ZADD', KEYS[2], expiry, task_id)
redis.call('ZADD', KEYS[3], expiry, task_id)
if import_id ~= '' then
  redis.call('ZADD', KEYS[4], expiry, task_id)
end
redis.call('HSET', KEYS[5], 'workspace_id', ws, 'organization_id', org, 'import_id', import_id)
redis.call('EXPIRE', KEYS[5], ttl + 120)
return 1
"""

_RELEASE_LEASE_LUA = """
local meta = redis.call('HGETALL', KEYS[1])
if #meta == 0 then return 0 end
local ws = nil
local org = nil
local import_id = nil
for i = 1, #meta, 2 do
  if meta[i] == 'workspace_id' then ws = meta[i + 1] end
  if meta[i] == 'organization_id' then org = meta[i + 1] end
  if meta[i] == 'import_id' then import_id = meta[i + 1] end
end
local task_id = ARGV[1]
if ws and ws ~= '' then redis.call('ZREM', 'platform_import:lease:ws:' .. ws, task_id) end
if org and org ~= '' then redis.call('ZREM', 'platform_import:lease:org:' .. org, task_id) end
redis.call('ZREM', 'platform_import:lease:global', task_id)
if import_id and import_id ~= '' then
  redis.call('ZREM', 'platform_import:lease:import:' .. import_id, task_id)
end
redis.call('DEL', KEYS[1])
return 1
"""

_RENEW_LEASE_LUA = """
local now = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local task_id = ARGV[3]
local expiry = now + ttl
local meta = redis.call('HGETALL', KEYS[1])
if #meta == 0 then return 0 end
local ws = nil
local org = nil
local import_id = nil
for i = 1, #meta, 2 do
  if meta[i] == 'workspace_id' then ws = meta[i + 1] end
  if meta[i] == 'organization_id' then org = meta[i + 1] end
  if meta[i] == 'import_id' then import_id = meta[i + 1] end
end
if ws and ws ~= '' then redis.call('ZADD', 'platform_import:lease:ws:' .. ws, expiry, task_id) end
if org and org ~= '' then redis.call('ZADD', 'platform_import:lease:org:' .. org, expiry, task_id) end
redis.call('ZADD', 'platform_import:lease:global', expiry, task_id)
if import_id and import_id ~= '' then
  redis.call('ZADD', 'platform_import:lease:import:' .. import_id, expiry, task_id)
end
redis.call('EXPIRE', KEYS[1], ttl + 120)
return 1
"""

_TRANSFER_LEASE_LUA = """
local now = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local old_id = ARGV[3]
local new_id = ARGV[4]
local meta = redis.call('HGETALL', KEYS[1])
if #meta == 0 then return 0 end
local ws = nil
local org = nil
local import_id = nil
for i = 1, #meta, 2 do
  if meta[i] == 'workspace_id' then ws = meta[i + 1] end
  if meta[i] == 'organization_id' then org = meta[i + 1] end
  if meta[i] == 'import_id' then import_id = meta[i + 1] end
end
local expiry = now + ttl
if ws and ws ~= '' then
  redis.call('ZREM', 'platform_import:lease:ws:' .. ws, old_id)
  redis.call('ZADD', 'platform_import:lease:ws:' .. ws, expiry, new_id)
end
if org and org ~= '' then
  redis.call('ZREM', 'platform_import:lease:org:' .. org, old_id)
  redis.call('ZADD', 'platform_import:lease:org:' .. org, expiry, new_id)
end
redis.call('ZREM', 'platform_import:lease:global', old_id)
redis.call('ZADD', 'platform_import:lease:global', expiry, new_id)
if import_id and import_id ~= '' then
  redis.call('ZREM', 'platform_import:lease:import:' .. import_id, old_id)
  redis.call('ZADD', 'platform_import:lease:import:' .. import_id, expiry, new_id)
end
redis.call('DEL', KEYS[1])
redis.call('HSET', KEYS[2], 'workspace_id', ws or '', 'organization_id', org or '', 'import_id', import_id or '')
redis.call('EXPIRE', KEYS[2], ttl + 120)
return 1
"""

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


def acquire_platform_lease(
    *,
    workspace_id: UUID,
    organization_id: UUID,
    call_import_id: UUID | str,
    celery_task_id: str,
) -> bool:
    """Take one in-flight lease. Redis errors refuse the slot."""
    try:
        acquired = _client().eval(
            _ACQUIRE_LEASE_LUA,
            5,
            _lease_ws_key(workspace_id),
            _lease_org_key(organization_id),
            _lease_global_key(),
            _lease_import_key(call_import_id),
            _lease_meta_key(celery_task_id),
            str(time.time()),
            str(int(settings.PLATFORM_IMPORT_LEASE_SECONDS)),
            str(settings.PLATFORM_IMPORT_WORKSPACE_INFLIGHT_LIMIT),
            str(settings.PLATFORM_IMPORT_ORG_INFLIGHT_LIMIT),
            str(settings.PLATFORM_IMPORT_GLOBAL_INFLIGHT_LIMIT),
            str(settings.PLATFORM_IMPORT_PER_IMPORT_INFLIGHT_LIMIT),
            celery_task_id,
            str(workspace_id),
            str(organization_id),
            str(call_import_id),
        )
        return bool(int(acquired or 0))
    except redis.RedisError as exc:
        logger.warning("platform import lease acquire failed: {}", exc)
        return False


def acquire_platform_import_slot(
    *,
    workspace_id: UUID,
    organization_id: UUID,
    celery_task_id: str,
    call_import_id: UUID | str | None = None,
) -> bool:
    if call_import_id is None:
        return False
    return acquire_platform_lease(
        workspace_id=workspace_id,
        organization_id=organization_id,
        call_import_id=call_import_id,
        celery_task_id=celery_task_id,
    )


def release_platform_lease(celery_task_id: str) -> None:
    if not celery_task_id:
        return
    try:
        _client().eval(
            _RELEASE_LEASE_LUA,
            1,
            _lease_meta_key(celery_task_id),
            celery_task_id,
        )
    except redis.RedisError as exc:
        logger.warning("platform import lease release failed: {}", exc)


def release_platform_import_slot(celery_task_id: str) -> None:
    release_platform_lease(celery_task_id)


def renew_platform_lease(celery_task_id: str) -> bool:
    if not celery_task_id:
        return False
    try:
        renewed = _client().eval(
            _RENEW_LEASE_LUA,
            1,
            _lease_meta_key(celery_task_id),
            str(time.time()),
            str(int(settings.PLATFORM_IMPORT_LEASE_SECONDS)),
            celery_task_id,
        )
        return bool(int(renewed or 0))
    except redis.RedisError as exc:
        logger.warning("platform import lease renew failed: {}", exc)
        return False


def transfer_platform_lease(old_task_id: str, new_task_id: str) -> bool:
    try:
        moved = _client().eval(
            _TRANSFER_LEASE_LUA,
            2,
            _lease_meta_key(old_task_id),
            _lease_meta_key(new_task_id),
            str(time.time()),
            str(int(settings.PLATFORM_IMPORT_LEASE_SECONDS)),
            old_task_id,
            new_task_id,
        )
        return bool(int(moved or 0))
    except redis.RedisError as exc:
        logger.warning("platform import lease transfer failed: {}", exc)
        return False


def lease_is_active(celery_task_id: str) -> bool:
    if not celery_task_id:
        return False
    try:
        score = _client().zscore(_lease_global_key(), celery_task_id)
    except redis.RedisError:
        return False
    if score is None:
        return False
    return float(score) > time.time()


def read_create_idempotency(workspace_id: UUID | str, key: str) -> str | None:
    if not key:
        return None
    try:
        raw = _client().get(f"platform_import:create:{workspace_id}:{key}")
    except redis.RedisError:
        return None
    if not raw:
        return None
    text = raw.decode() if isinstance(raw, bytes) else str(raw)
    return text or None


def store_create_idempotency(workspace_id: UUID | str, key: str, import_id: str) -> None:
    try:
        _client().set(f"platform_import:create:{workspace_id}:{key}", import_id, ex=86400)
    except redis.RedisError as exc:
        logger.warning("platform import idempotency store failed: {}", exc)


def platform_import_runtime_stats() -> dict:
    return {
        "imports_depth": queue_depth("imports"),
        "control_depth": queue_depth("import-control"),
        "global_leases": lease_count(_lease_global_key()),
    }


def lease_count(key: str) -> int:
    try:
        now = time.time()
        client = _client()
        client.zremrangebyscore(key, "-inf", now)
        return int(client.zcard(key) or 0)
    except redis.RedisError:
        return 0


def consume_platform_api_token(
    integration_id: UUID,
    speed: Optional[str],
    *,
    cost: int = 1,
    member: str | None = None,
) -> TokenResult:
    rpm = rpm_for_speed(speed)
    try:
        if _client().get(_auth_fail_key(integration_id)):
            return TokenResult(False, wait_seconds=60)
    except redis.RedisError:
        return TokenResult(False, wait_seconds=5)
    token_member = member or f"{time.time()}:{id(integration_id)}"
    try:
        allowed = _client().eval(
            _TOKEN_LUA,
            1,
            _token_key(integration_id),
            str(time.time()),
            "60",
            str(rpm),
            str(max(1, int(cost))),
            token_member,
        )
        if int(allowed or 0):
            return TokenResult(True)
        return TokenResult(False, wait_seconds=1)
    except redis.RedisError as exc:
        logger.warning("platform token bucket failed: {}", exc)
        return TokenResult(False, wait_seconds=5)


def record_platform_auth_failure(integration_id: UUID) -> int:
    key = _auth_fail_key(integration_id)
    try:
        fails = int(_client().incr(key))
        _client().expire(key, 300)
        if fails >= 20:
            _client().setex(f"platform_import:paused_cred:{integration_id}", 3600, "1")
        return fails
    except redis.RedisError:
        return 0


def clear_platform_auth_failures(integration_id: UUID) -> None:
    try:
        _client().delete(_auth_fail_key(integration_id))
        _client().delete(f"platform_import:paused_cred:{integration_id}")
    except redis.RedisError:
        pass


def _slice_lock_key(call_import_id: UUID | str, slice_id: int) -> str:
    return f"platform_import:slice_lock:{call_import_id}:{slice_id}"


def slice_lock_ttl_seconds() -> int:
    return int(settings.PLATFORM_IMPORT_DISCOVERY_SLICE_STALE_MINUTES) * 60 + 300


_ACQUIRE_SLICE_LOCK_LUA = """
local current = redis.call('GET', KEYS[1])
if current == false then
  redis.call('SET', KEYS[1], ARGV[1], 'EX', tonumber(ARGV[2]))
  return 1
end
if current == ARGV[1] then
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
  return 1
end
return 0
"""

_TRANSFER_SLICE_LOCK_LUA = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then
  return 0
end
redis.call('SET', KEYS[1], ARGV[2], 'EX', tonumber(ARGV[3]))
return 1
"""

_RELEASE_SLICE_LOCK_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


def acquire_slice_lock(call_import_id: UUID | str, slice_id: int, owner: str) -> bool:
    """One owner per discovery day. A second caller does not get a task."""
    try:
        acquired = _client().eval(
            _ACQUIRE_SLICE_LOCK_LUA,
            1,
            _slice_lock_key(call_import_id, slice_id),
            owner,
            str(slice_lock_ttl_seconds()),
        )
        return bool(int(acquired or 0))
    except redis.RedisError as exc:
        logger.warning("platform slice lock acquire failed: {}", exc)
        return False


def slice_lock_owner(call_import_id: UUID | str, slice_id: int) -> str | None:
    try:
        value = _client().get(_slice_lock_key(call_import_id, slice_id))
    except redis.RedisError as exc:
        logger.warning("platform slice lock read failed: {}", exc)
        return None
    if value is None:
        return None
    return str(value)


def transfer_slice_lock(
    call_import_id: UUID | str,
    slice_id: int,
    owner: str,
    new_owner: str,
) -> bool:
    try:
        moved = _client().eval(
            _TRANSFER_SLICE_LOCK_LUA,
            1,
            _slice_lock_key(call_import_id, slice_id),
            owner,
            new_owner,
            str(slice_lock_ttl_seconds()),
        )
        return bool(int(moved or 0))
    except redis.RedisError as exc:
        logger.warning("platform slice lock transfer failed: {}", exc)
        return False


def release_slice_lock(call_import_id: UUID | str, slice_id: int, owner: str) -> None:
    try:
        _client().eval(
            _RELEASE_SLICE_LOCK_LUA,
            1,
            _slice_lock_key(call_import_id, slice_id),
            owner,
        )
    except redis.RedisError as exc:
        logger.warning("platform slice lock release failed: {}", exc)


def renew_slice_lock(call_import_id: UUID | str, slice_id: int) -> None:
    try:
        _client().expire(_slice_lock_key(call_import_id, slice_id), slice_lock_ttl_seconds())
    except redis.RedisError as exc:
        logger.warning("platform slice lock renew failed: {}", exc)


def force_release_slice_lock(call_import_id: UUID | str, slice_id: int) -> None:
    try:
        _client().delete(_slice_lock_key(call_import_id, slice_id))
    except redis.RedisError as exc:
        logger.warning("platform slice lock force release failed: {}", exc)


def queue_depth(name: str) -> int | None:
    try:
        return int(_client().llen(name) or 0)
    except redis.RedisError as exc:
        logger.warning("platform queue depth failed queue={}: {}", name, exc)
        return None


def imports_queue_depth() -> int | None:
    return queue_depth("imports")


def discovery_enqueue_blocked() -> bool:
    depth = imports_queue_depth()
    cap = int(settings.PLATFORM_IMPORT_DISCOVERY_QUEUE_CAP)
    if depth is None:
        logger.error("platform discovery enqueue refused queue_depth=unknown")
        return True
    if depth >= cap:
        logger.error(
            "platform discovery enqueue refused queue_depth={} cap={}",
            depth,
            cap,
        )
        return True
    return False


def hydrate_enqueue_blocked() -> bool:
    depth = imports_queue_depth()
    cap = int(settings.PLATFORM_IMPORT_HYDRATE_QUEUE_CAP)
    if depth is None:
        logger.error("platform hydrate enqueue refused queue_depth=unknown")
        return True
    if depth >= cap:
        logger.error(
            "platform hydrate enqueue refused queue_depth={} cap={}",
            depth,
            cap,
        )
        return True
    return False


def credential_import_paused(integration_id: UUID) -> bool:
    try:
        return bool(_client().get(f"platform_import:paused_cred:{integration_id}"))
    except redis.RedisError:
        return False
