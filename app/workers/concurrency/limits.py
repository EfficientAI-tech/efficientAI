"""Redis-backed in-flight limits for call-import evaluation work."""

from __future__ import annotations

import time
from uuid import UUID

import redis
from loguru import logger

from app.config import settings

_EVAL_SLOT_TTL_SECONDS = 20 * 60  # 2× the eval/transcribe hard time limit
_IMPORT_SLOT_TTL_SECONDS = 20 * 60  # 2× the import hard time limit

_redis_client: redis.Redis | None = None

_ACQUIRE_LEASE_LUA = """
local now = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local ws_limit = tonumber(ARGV[3])
local org_limit = tonumber(ARGV[4])
local glob_limit = tonumber(ARGV[5])
local extra_limit = tonumber(ARGV[6])
local task_id = ARGV[7]
local ws = ARGV[8]
local org = ARGV[9]
local extra_id = ARGV[10]
local ws_prefix = ARGV[11]
local org_prefix = ARGV[12]
local glob_key = ARGV[13]
local extra_prefix = ARGV[14]
local expiry = now + ttl
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now)
redis.call('ZREMRANGEBYSCORE', KEYS[3], '-inf', now)
if extra_id ~= '' then
  redis.call('ZREMRANGEBYSCORE', KEYS[4], '-inf', now)
end
if redis.call('ZCARD', KEYS[1]) >= ws_limit then return 0 end
if redis.call('ZCARD', KEYS[2]) >= org_limit then return 0 end
if redis.call('ZCARD', KEYS[3]) >= glob_limit then return 0 end
if extra_id ~= '' and extra_limit > 0 and redis.call('ZCARD', KEYS[4]) >= extra_limit then
  return 0
end
redis.call('ZADD', KEYS[1], expiry, task_id)
redis.call('ZADD', KEYS[2], expiry, task_id)
redis.call('ZADD', KEYS[3], expiry, task_id)
if extra_id ~= '' then
  redis.call('ZADD', KEYS[4], expiry, task_id)
end
redis.call('HSET', KEYS[5], 'workspace_id', ws, 'organization_id', org, 'evaluation_id', extra_id)
redis.call('EXPIRE', KEYS[5], ttl + 120)
return 1
"""

_RELEASE_LEASE_LUA = """
local meta = redis.call('HGETALL', KEYS[1])
if #meta == 0 then return 0 end
local ws = nil
local org = nil
local evaluation_id = nil
for i = 1, #meta, 2 do
  if meta[i] == 'workspace_id' then ws = meta[i + 1] end
  if meta[i] == 'organization_id' then org = meta[i + 1] end
  if meta[i] == 'evaluation_id' then evaluation_id = meta[i + 1] end
end
local task_id = ARGV[1]
local ws_prefix = ARGV[2]
local org_prefix = ARGV[3]
local glob_key = ARGV[4]
local job_prefix = ARGV[5]
if ws and ws ~= '' then redis.call('ZREM', ws_prefix .. ws, task_id) end
if org and org ~= '' then redis.call('ZREM', org_prefix .. org, task_id) end
redis.call('ZREM', glob_key, task_id)
if evaluation_id and evaluation_id ~= '' and job_prefix ~= '' then
  redis.call('ZREM', job_prefix .. evaluation_id, task_id)
end
redis.call('DEL', KEYS[1])
return 1
"""


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def _eval_ws_lease_key(workspace_id: UUID | str) -> str:
    return f"eval:lease:ws:{workspace_id}"


def _eval_org_lease_key(organization_id: UUID | str) -> str:
    return f"eval:lease:org:{organization_id}"


def _eval_global_lease_key() -> str:
    return "eval:lease:global"


def _eval_job_lease_key(evaluation_id: UUID | str) -> str:
    return f"eval:lease:job:{evaluation_id}"


def _eval_meta_key(celery_task_id: str) -> str:
    return f"eval:lease:meta:{celery_task_id}"


def _import_ws_lease_key(workspace_id: UUID | str) -> str:
    return f"import:lease:ws:{workspace_id}"


def _import_org_lease_key(organization_id: UUID | str) -> str:
    return f"import:lease:org:{organization_id}"


def _import_global_lease_key() -> str:
    return "import:lease:global"


def _import_meta_key(celery_task_id: str) -> str:
    return f"import:lease:meta:{celery_task_id}"


def _lease_inflight(client: redis.Redis, zset_key: str) -> int:
    now = time.time()
    try:
        client.zremrangebyscore(zset_key, "-inf", now)
        return int(client.zcard(zset_key) or 0)
    except redis.RedisError:
        return 0


_UNUSED_LEASE_ZSET = "call_import:lease:_unused"


def _acquire_lease(
    *,
    ws_zset: str,
    org_zset: str,
    glob_zset: str,
    extra_zset: str | None,
    meta_key: str,
    celery_task_id: str,
    workspace_id: UUID | str,
    organization_id: UUID | str,
    ws_limit: int,
    org_limit: int,
    glob_limit: int,
    extra_limit: int,
    extra_id: str,
    ttl_seconds: int,
    ws_prefix: str,
    org_prefix: str,
    glob_key_literal: str,
    extra_prefix: str,
    job_prefix: str,
) -> bool:
    try:
        client = _get_redis()
        extra_key = extra_zset if extra_zset is not None else _UNUSED_LEASE_ZSET
        keys = [
            ws_zset,
            org_zset,
            glob_zset,
            extra_key,
            meta_key,
        ]
        acquired = client.eval(
            _ACQUIRE_LEASE_LUA,
            len(keys),
            *keys,
            str(time.time()),
            str(ttl_seconds),
            str(ws_limit),
            str(org_limit),
            str(glob_limit),
            str(extra_limit),
            celery_task_id,
            str(workspace_id),
            str(organization_id),
            extra_id,
            ws_prefix,
            org_prefix,
            glob_key_literal,
            extra_prefix,
        )
        return bool(int(acquired or 0))
    except redis.RedisError as exc:
        logger.warning("Slot lease acquire failed (Redis error): {}", exc)
        return False


def _release_lease(
    *,
    meta_key: str,
    celery_task_id: str,
    ws_prefix: str,
    org_prefix: str,
    glob_key_literal: str,
    job_prefix: str,
) -> None:
    if not celery_task_id:
        return
    try:
        client = _get_redis()
        if not client.exists(meta_key):
            return
        client.eval(
            _RELEASE_LEASE_LUA,
            1,
            meta_key,
            celery_task_id,
            ws_prefix,
            org_prefix,
            glob_key_literal,
            job_prefix,
        )
    except redis.RedisError as exc:
        logger.warning(
            "Slot lease release failed for task {} (Redis error): {}",
            celery_task_id,
            exc,
        )


def acquire_eval_slot(
    *,
    workspace_id: UUID | str,
    organization_id: UUID | str,
    celery_task_id: str,
    evaluation_id: UUID | str | None = None,
) -> bool:
    """Try to acquire one eval/transcribe in-flight slot. Returns False when at cap."""
    eval_id_str = str(evaluation_id) if evaluation_id else ""
    extra_zset = (
        _eval_job_lease_key(evaluation_id)
        if evaluation_id and settings.EVAL_JOB_INFLIGHT_LIMIT > 0
        else None
    )
    extra_limit = (
        int(settings.EVAL_JOB_INFLIGHT_LIMIT)
        if evaluation_id and settings.EVAL_JOB_INFLIGHT_LIMIT > 0
        else 0
    )
    return _acquire_lease(
        ws_zset=_eval_ws_lease_key(workspace_id),
        org_zset=_eval_org_lease_key(organization_id),
        glob_zset=_eval_global_lease_key(),
        extra_zset=extra_zset,
        meta_key=_eval_meta_key(celery_task_id),
        celery_task_id=celery_task_id,
        workspace_id=workspace_id,
        organization_id=organization_id,
        ws_limit=int(settings.EVAL_WORKSPACE_INFLIGHT_LIMIT),
        org_limit=int(settings.EVAL_ORG_INFLIGHT_LIMIT),
        glob_limit=int(settings.EVAL_GLOBAL_INFLIGHT_LIMIT),
        extra_limit=extra_limit,
        extra_id=eval_id_str if extra_zset else "",
        ttl_seconds=_EVAL_SLOT_TTL_SECONDS,
        ws_prefix="eval:lease:ws:",
        org_prefix="eval:lease:org:",
        glob_key_literal=_eval_global_lease_key(),
        extra_prefix="eval:lease:job:",
        job_prefix="eval:lease:job:",
    )


def acquire_import_slot(
    *,
    workspace_id: UUID | str,
    organization_id: UUID | str,
    celery_task_id: str,
) -> bool:
    """Try to acquire one recording-fetch in-flight slot. Returns False when at cap."""
    return _acquire_lease(
        ws_zset=_import_ws_lease_key(workspace_id),
        org_zset=_import_org_lease_key(organization_id),
        glob_zset=_import_global_lease_key(),
        extra_zset=None,
        meta_key=_import_meta_key(celery_task_id),
        celery_task_id=celery_task_id,
        workspace_id=workspace_id,
        organization_id=organization_id,
        ws_limit=int(settings.IMPORT_WORKSPACE_INFLIGHT_LIMIT),
        org_limit=int(settings.IMPORT_ORG_INFLIGHT_LIMIT),
        glob_limit=int(settings.IMPORT_GLOBAL_INFLIGHT_LIMIT),
        extra_limit=0,
        extra_id="",
        ttl_seconds=_IMPORT_SLOT_TTL_SECONDS,
        ws_prefix="import:lease:ws:",
        org_prefix="import:lease:org:",
        glob_key_literal=_import_global_lease_key(),
        extra_prefix="",
        job_prefix="",
    )


def read_inflight_count(key: str) -> int:
    """Read active lease count for a zset key (returns 0 on error)."""
    try:
        return _lease_inflight(_get_redis(), key)
    except redis.RedisError:
        return 0


def read_global_inflight() -> int:
    return read_inflight_count(_eval_global_lease_key())


def read_import_global_inflight() -> int:
    return read_inflight_count(_import_global_lease_key())


def read_org_inflight(organization_id: UUID | str) -> int:
    return read_inflight_count(_eval_org_lease_key(organization_id))


def read_workspace_inflight(workspace_id: UUID | str) -> int:
    return read_inflight_count(_eval_ws_lease_key(workspace_id))


def read_job_inflight(evaluation_id: UUID | str) -> int:
    return read_inflight_count(_eval_job_lease_key(evaluation_id))


def slot_registered_for_task(celery_task_id: str) -> bool:
    try:
        client = _get_redis()
        return bool(client.exists(_eval_meta_key(celery_task_id))) or bool(
            client.exists(_import_meta_key(celery_task_id))
        )
    except redis.RedisError:
        return False


def release_eval_slot_for_celery_task(celery_task_id: str) -> None:
    """Release the slot held by a dispatched eval/transcribe Celery task."""
    _release_lease(
        meta_key=_eval_meta_key(celery_task_id),
        celery_task_id=celery_task_id,
        ws_prefix="eval:lease:ws:",
        org_prefix="eval:lease:org:",
        glob_key_literal=_eval_global_lease_key(),
        job_prefix="eval:lease:job:",
    )


def release_import_slot_for_celery_task(celery_task_id: str) -> None:
    """Release the slot held by a dispatched recording-fetch Celery task."""
    _release_lease(
        meta_key=_import_meta_key(celery_task_id),
        celery_task_id=celery_task_id,
        ws_prefix="import:lease:ws:",
        org_prefix="import:lease:org:",
        glob_key_literal=_import_global_lease_key(),
        job_prefix="",
    )
