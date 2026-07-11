"""Redis-backed in-flight limits for call-import evaluation work."""

from __future__ import annotations

from uuid import UUID

import redis
from loguru import logger

from app.config import settings

_EVAL_SLOT_TTL_SECONDS = 20 * 60  # 2× the eval/transcribe hard time limit

_redis_client: redis.Redis | None = None

_ACQUIRE_LUA = """
local ws_key = KEYS[1]
local org_key = KEYS[2]
local glob_key = KEYS[3]
local task_key = KEYS[4]
local ws_limit = tonumber(ARGV[1])
local org_limit = tonumber(ARGV[2])
local glob_limit = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])
local ws = tonumber(redis.call('GET', ws_key) or '0')
local org = tonumber(redis.call('GET', org_key) or '0')
local glob = tonumber(redis.call('GET', glob_key) or '0')
if ws >= ws_limit then return 0 end
if org >= org_limit then return 0 end
if glob >= glob_limit then return 0 end
redis.call('INCR', ws_key)
redis.call('EXPIRE', ws_key, ttl)
redis.call('INCR', org_key)
redis.call('EXPIRE', org_key, ttl)
redis.call('INCR', glob_key)
redis.call('EXPIRE', glob_key, ttl)
redis.call('HSET', task_key, 'workspace_id', ARGV[5], 'organization_id', ARGV[6])
redis.call('EXPIRE', task_key, ttl)
return 1
"""

_RELEASE_LUA = """
local ws_key = KEYS[1]
local org_key = KEYS[2]
local glob_key = KEYS[3]
local task_key = KEYS[4]
if redis.call('EXISTS', task_key) == 0 then return 0 end
redis.call('DEL', task_key)
local function decr_min_zero(key)
  local v = tonumber(redis.call('DECR', key))
  if v < 0 then redis.call('SET', key, 0) end
end
decr_min_zero(ws_key)
decr_min_zero(org_key)
decr_min_zero(glob_key)
return 1
"""


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def _workspace_key(workspace_id: UUID | str) -> str:
    return f"eval:inflight:workspace:{workspace_id}"


def _org_key(organization_id: UUID | str) -> str:
    return f"eval:inflight:org:{organization_id}"


def _global_key() -> str:
    return "eval:inflight:global"


def _task_key(celery_task_id: str) -> str:
    return f"eval:slot:task:{celery_task_id}"


def acquire_eval_slot(
    *,
    workspace_id: UUID | str,
    organization_id: UUID | str,
    celery_task_id: str,
) -> bool:
    """Try to acquire one eval/transcribe in-flight slot. Returns False when at cap."""
    try:
        client = _get_redis()
        acquired = client.eval(
            _ACQUIRE_LUA,
            4,
            _workspace_key(workspace_id),
            _org_key(organization_id),
            _global_key(),
            _task_key(celery_task_id),
            str(settings.EVAL_WORKSPACE_INFLIGHT_LIMIT),
            str(settings.EVAL_ORG_INFLIGHT_LIMIT),
            str(settings.EVAL_GLOBAL_INFLIGHT_LIMIT),
            str(_EVAL_SLOT_TTL_SECONDS),
            str(workspace_id),
            str(organization_id),
        )
        return bool(int(acquired or 0))
    except redis.RedisError as exc:
        logger.warning("Eval slot acquire failed (Redis error): {}", exc)
        # Fail open so work is not permanently blocked by Redis hiccups.
        return True


def slot_registered_for_task(celery_task_id: str) -> bool:
    try:
        return bool(_get_redis().exists(_task_key(celery_task_id)))
    except redis.RedisError:
        return False


def release_eval_slot_for_celery_task(celery_task_id: str) -> None:
    """Release the slot held by a dispatched eval/transcribe Celery task."""
    if not celery_task_id:
        return
    task_key = _task_key(celery_task_id)
    try:
        client = _get_redis()
        mapping = client.hgetall(task_key)
        if not mapping:
            return
        workspace_id = mapping.get("workspace_id")
        organization_id = mapping.get("organization_id")
        if not workspace_id or not organization_id:
            client.delete(task_key)
            return
        client.eval(
            _RELEASE_LUA,
            4,
            _workspace_key(workspace_id),
            _org_key(organization_id),
            _global_key(),
            task_key,
        )
    except redis.RedisError as exc:
        logger.warning(
            "Eval slot release failed for task {} (Redis error): {}",
            celery_task_id,
            exc,
        )
