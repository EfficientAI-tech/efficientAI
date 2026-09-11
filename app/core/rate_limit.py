"""Redis sliding-window rate limits for trace ingest routes."""

from __future__ import annotations

import time
from typing import Optional
from uuid import UUID

import redis
from fastapi import Depends, HTTPException, status

from app.config import settings
from app.core.auth import Principal, get_principal

_redis_client: Optional[redis.Redis] = None
_KEY_PREFIX = "traces:rate"


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def _rate_key(principal: Principal, route_group: str) -> str:
    if principal.api_key_id:
        subject = f"api_key:{principal.api_key_id}"
    elif principal.user_id:
        subject = f"user:{principal.user_id}"
    else:
        subject = f"org:{principal.organization_id}"
    return f"{_KEY_PREFIX}:{route_group}:{subject}"


def check_trace_rate_limit(principal: Principal, route_group: str = "ingest") -> None:
    if not settings.TRACES_RATE_LIMIT_ENFORCE:
        return
    limit = max(1, int(settings.TRACES_RATE_LIMIT_PER_MINUTE))
    window = 60
    now = int(time.time())
    key = _rate_key(principal, route_group)
    try:
        pipe = _get_redis().pipeline()
        pipe.zremrangebyscore(key, 0, now - window)
        pipe.zadd(key, {str(now): now})
        pipe.zcard(key)
        pipe.expire(key, window + 5)
        _, _, count, _ = pipe.execute()
    except redis.RedisError:
        return
    if int(count or 0) > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Trace ingest rate limit exceeded",
            headers={"Retry-After": str(window)},
        )


def enforce_trace_ingest_rate_limit(
    principal: Principal = Depends(get_principal),
) -> Principal:
    check_trace_rate_limit(principal, route_group="ingest")
    return principal


def enforce_trace_session_rate_limit(
    principal: Principal = Depends(get_principal),
) -> Principal:
    check_trace_rate_limit(principal, route_group="sessions")
    return principal
