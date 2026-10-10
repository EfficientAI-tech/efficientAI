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

SPEED_RPM = {
    "gentle": 30,
    "standard": 120,
    "fast": 300,
}


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


def rpm_for_speed(speed: Optional[str]) -> int:
    key = (speed or "standard").strip().lower()
    return SPEED_RPM.get(key, SPEED_RPM["standard"])


def acquire_platform_import_slot(
    *,
    workspace_id: UUID,
    organization_id: UUID,
    celery_task_id: str,
) -> bool:
    from app.workers.concurrency.limits import _ACQUIRE_LUA

    try:
        client = _client()
        acquired = client.eval(
            _ACQUIRE_LUA,
            5,
            _ws_key(workspace_id),
            _org_key(organization_id),
            _global_key(),
            _task_key(celery_task_id),
            _task_key(celery_task_id),
            str(settings.PLATFORM_IMPORT_WORKSPACE_INFLIGHT_LIMIT),
            str(settings.PLATFORM_IMPORT_ORG_INFLIGHT_LIMIT),
            str(settings.PLATFORM_IMPORT_GLOBAL_INFLIGHT_LIMIT),
            str(_PLATFORM_SLOT_TTL_SECONDS),
            "0",
            "",
            str(workspace_id),
            str(organization_id),
        )
        return bool(int(acquired or 0))
    except redis.RedisError as exc:
        logger.warning("platform import slot acquire failed: {}", exc)
        return True


def release_platform_import_slot(celery_task_id: str) -> None:
    from app.workers.concurrency.limits import release_import_slot_for_celery_task

    try:
        client = _client()
        meta_key = _task_key(celery_task_id)
        meta = client.hgetall(meta_key)
        if meta:
            ws = meta.get("workspace_id")
            org = meta.get("organization_id")
            if ws and org:
                client.decr(_ws_key(ws))
                client.decr(_org_key(org))
                client.decr(_global_key())
            client.delete(meta_key)
    except redis.RedisError:
        pass
    release_import_slot_for_celery_task(celery_task_id)


def consume_platform_api_token(integration_id: UUID, speed: Optional[str]) -> TokenResult:
    rpm = rpm_for_speed(speed)
    if _client().get(_auth_fail_key(integration_id)):
        return TokenResult(False, wait_seconds=60)
    key = _token_key(integration_id)
    now = time.time()
    window = 60.0
    try:
        pipe = _client().pipeline()
        pipe.zremrangebyscore(key, 0, now - window)
        pipe.zcard(key)
        pipe.zadd(key, {str(now): now})
        pipe.expire(key, int(window * 2))
        results = pipe.execute()
        count = int(results[1] or 0)
        if count >= rpm:
            return TokenResult(False, wait_seconds=1)
        return TokenResult(True)
    except redis.RedisError as exc:
        logger.debug("platform token bucket skipped: {}", exc)
        return TokenResult(True)


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


def credential_import_paused(integration_id: UUID) -> bool:
    try:
        return bool(_client().get(f"platform_import:paused_cred:{integration_id}"))
    except redis.RedisError:
        return False
