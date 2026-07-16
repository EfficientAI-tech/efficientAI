"""Redis-backed in-flight limits for call-import evaluation work."""

from __future__ import annotations

from uuid import UUID

import redis
from loguru import logger

from app.config import settings

_EVAL_SLOT_TTL_SECONDS = 20 * 60  # 2× the eval/transcribe hard time limit
_IMPORT_SLOT_TTL_SECONDS = 20 * 60  # 2× the import hard time limit

_redis_client: redis.Redis | None = None

_ACQUIRE_LUA = """
local ws_key = KEYS[1]
local org_key = KEYS[2]
local glob_key = KEYS[3]
local task_key = KEYS[4]
local job_key = KEYS[5]
local ws_limit = tonumber(ARGV[1])
local org_limit = tonumber(ARGV[2])
local glob_limit = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])
local job_limit = tonumber(ARGV[5])
local evaluation_id = ARGV[6]
local ws = tonumber(redis.call('GET', ws_key) or '0')
local org = tonumber(redis.call('GET', org_key) or '0')
local glob = tonumber(redis.call('GET', glob_key) or '0')
if ws >= ws_limit then return 0 end
if org >= org_limit then return 0 end
if glob >= glob_limit then return 0 end
if evaluation_id ~= '' and job_limit > 0 then
  local job = tonumber(redis.call('GET', job_key) or '0')
  if job >= job_limit then return 0 end
end
redis.call('INCR', ws_key)
redis.call('EXPIRE', ws_key, ttl)
redis.call('INCR', org_key)
redis.call('EXPIRE', org_key, ttl)
redis.call('INCR', glob_key)
redis.call('EXPIRE', glob_key, ttl)
if evaluation_id ~= '' and job_limit > 0 then
  redis.call('INCR', job_key)
  redis.call('EXPIRE', job_key, ttl)
  redis.call('HSET', task_key, 'evaluation_id', evaluation_id)
end
redis.call('HSET', task_key, 'workspace_id', ARGV[7], 'organization_id', ARGV[8])
redis.call('EXPIRE', task_key, ttl)
return 1
"""

_RELEASE_LUA = """
local ws_key = KEYS[1]
local org_key = KEYS[2]
local glob_key = KEYS[3]
local task_key = KEYS[4]
local job_key = KEYS[5]
if redis.call('EXISTS', task_key) == 0 then return 0 end
local evaluation_id = redis.call('HGET', task_key, 'evaluation_id')
redis.call('DEL', task_key)
local function decr_min_zero(key)
  local v = tonumber(redis.call('DECR', key))
  if v < 0 then redis.call('SET', key, 0) end
end
decr_min_zero(ws_key)
decr_min_zero(org_key)
decr_min_zero(glob_key)
if evaluation_id then
  decr_min_zero(job_key)
end
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


def _job_key(evaluation_id: UUID | str) -> str:
    return f"eval:inflight:job:{evaluation_id}"


def _task_key(celery_task_id: str) -> str:
    return f"eval:slot:task:{celery_task_id}"


def _import_workspace_key(workspace_id: UUID | str) -> str:
    return f"import:inflight:workspace:{workspace_id}"


def _import_org_key(organization_id: UUID | str) -> str:
    return f"import:inflight:org:{organization_id}"


def _import_global_key() -> str:
    return "import:inflight:global"


def _import_task_key(celery_task_id: str) -> str:
    return f"import:slot:task:{celery_task_id}"


def acquire_eval_slot(
    *,
    workspace_id: UUID | str,
    organization_id: UUID | str,
    celery_task_id: str,
    evaluation_id: UUID | str | None = None,
) -> bool:
    """Try to acquire one eval/transcribe in-flight slot. Returns False when at cap."""
    eval_id_str = str(evaluation_id) if evaluation_id else ""
    job_key = _job_key(evaluation_id) if evaluation_id else _task_key(celery_task_id)
    try:
        client = _get_redis()
        acquired = client.eval(
            _ACQUIRE_LUA,
            5,
            _workspace_key(workspace_id),
            _org_key(organization_id),
            _global_key(),
            _task_key(celery_task_id),
            job_key,
            str(settings.EVAL_WORKSPACE_INFLIGHT_LIMIT),
            str(settings.EVAL_ORG_INFLIGHT_LIMIT),
            str(settings.EVAL_GLOBAL_INFLIGHT_LIMIT),
            str(_EVAL_SLOT_TTL_SECONDS),
            str(settings.EVAL_JOB_INFLIGHT_LIMIT),
            eval_id_str,
            str(workspace_id),
            str(organization_id),
        )
        return bool(int(acquired or 0))
    except redis.RedisError as exc:
        logger.warning("Eval slot acquire failed (Redis error): {}", exc)
        # Fail open so work is not permanently blocked by Redis hiccups.
        return True


def acquire_import_slot(
    *,
    workspace_id: UUID | str,
    organization_id: UUID | str,
    celery_task_id: str,
) -> bool:
    """Try to acquire one recording-fetch in-flight slot. Returns False when at cap."""
    try:
        client = _get_redis()
        task_key = _import_task_key(celery_task_id)
        acquired = client.eval(
            _ACQUIRE_LUA,
            5,
            _import_workspace_key(workspace_id),
            _import_org_key(organization_id),
            _import_global_key(),
            task_key,
            task_key,
            str(settings.IMPORT_WORKSPACE_INFLIGHT_LIMIT),
            str(settings.IMPORT_ORG_INFLIGHT_LIMIT),
            str(settings.IMPORT_GLOBAL_INFLIGHT_LIMIT),
            str(_IMPORT_SLOT_TTL_SECONDS),
            "0",
            "",
            str(workspace_id),
            str(organization_id),
        )
        return bool(int(acquired or 0))
    except redis.RedisError as exc:
        logger.warning("Import slot acquire failed (Redis error): {}", exc)
        return True


def read_inflight_count(key: str) -> int:
    """Read a single Redis in-flight counter (returns 0 on error)."""
    try:
        return max(0, int(_get_redis().get(key) or 0))
    except (redis.RedisError, ValueError, TypeError):
        return 0


def read_global_inflight() -> int:
    return read_inflight_count(_global_key())


def read_import_global_inflight() -> int:
    return read_inflight_count(_import_global_key())


def read_org_inflight(organization_id: UUID | str) -> int:
    return read_inflight_count(_org_key(organization_id))


def read_workspace_inflight(workspace_id: UUID | str) -> int:
    return read_inflight_count(_workspace_key(workspace_id))


def read_job_inflight(evaluation_id: UUID | str) -> int:
    return read_inflight_count(_job_key(evaluation_id))


def slot_registered_for_task(celery_task_id: str) -> bool:
    try:
        client = _get_redis()
        return bool(client.exists(_task_key(celery_task_id))) or bool(
            client.exists(_import_task_key(celery_task_id))
        )
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
        evaluation_id = mapping.get("evaluation_id")
        if not workspace_id or not organization_id:
            client.delete(task_key)
            return
        job_key = _job_key(evaluation_id) if evaluation_id else task_key
        client.eval(
            _RELEASE_LUA,
            5,
            _workspace_key(workspace_id),
            _org_key(organization_id),
            _global_key(),
            task_key,
            job_key,
        )
    except redis.RedisError as exc:
        logger.warning(
            "Eval slot release failed for task {} (Redis error): {}",
            celery_task_id,
            exc,
        )


def release_import_slot_for_celery_task(celery_task_id: str) -> None:
    """Release the slot held by a dispatched recording-fetch Celery task."""
    if not celery_task_id:
        return
    task_key = _import_task_key(celery_task_id)
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
            5,
            _import_workspace_key(workspace_id),
            _import_org_key(organization_id),
            _import_global_key(),
            task_key,
            task_key,
        )
    except redis.RedisError as exc:
        logger.warning(
            "Import slot release failed for task {} (Redis error): {}",
            celery_task_id,
            exc,
        )
