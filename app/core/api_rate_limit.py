"""HTTP abuse rate limits (SaaS only when API_RATE_LIMIT_ENFORCE is true).

Self-hosted defaults keep API_RATE_LIMIT_ENFORCE=false so call imports, evals,
and bulk API traffic are not capped by this module.

When enforce is enabled (EfficientAI SaaS config.yml rate_limits.enforce: true):

  - Auth: POST /auth/login, POST /auth/register (per client IP)
  - Health: GET /health for anonymous IPs (LB/VPC peers exempt)
  - UI resource create: only routes listed in RESOURCE_CREATE_RATE_LIMIT_ROUTES

Does NOT apply to: call_imports*, evaluations*, evaluators*, traces ingest,
metric create, uploads, or any scale/bulk workflow.

Worker throughput (workers.eval_*, workers.import_*, telephony_import_credit_*)
is separate — Redis inflight caps, not HTTP 429. See env.example.
"""

from __future__ import annotations

import time
from typing import Callable, Optional
from uuid import UUID

import redis
from fastapi import Depends, HTTPException, Request, status

from app.config import settings
from app.core.auth import Principal, get_principal
from app.core.operational_access_middleware import (
    _resolved_trusted_ip,
    is_operational_access_allowed,
)

RESOURCE_CREATE_RATE_LIMIT_ROUTES: tuple[str, ...] = (
    "agents:create_agent",
    "personas:create_persona",
    "scenarios:create_scenario",
    "chat:chat_completion",
)

SCALE_EXEMPT_ROUTE_MODULE_PREFIXES: frozenset[str] = frozenset(
    {
        "call_import",
        "call_import_",
        "evaluation",
        "evaluator",
        "conversation_evaluation",
        "manual_evaluation",
    }
)

_redis_client: Optional[redis.Redis] = None
_KEY_PREFIX = "api:rate"


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def _client_ip(request: Request) -> str:
    resolved = _resolved_trusted_ip(request)
    if resolved:
        return resolved
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _sliding_window_count(key: str, window_seconds: int) -> int:
    now = int(time.time())
    pipe = _get_redis().pipeline()
    pipe.zremrangebyscore(key, 0, now - window_seconds)
    pipe.zadd(key, {f"{now}:{time.time_ns()}": now})
    pipe.zcard(key)
    pipe.expire(key, window_seconds + 5)
    _, _, count, _ = pipe.execute()
    return int(count or 0)


def _check_limit(key: str, limit: int, window_seconds: int) -> None:
    if limit <= 0:
        return
    try:
        count = _sliding_window_count(key, window_seconds)
    except redis.RedisError:
        return
    if count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(window_seconds)},
        )


def check_auth_rate_limit(request: Request) -> None:
    if not settings.API_RATE_LIMIT_ENFORCE:
        return
    ip = _client_ip(request)
    limit = max(1, int(settings.API_AUTH_RATE_LIMIT_PER_MINUTE))
    _check_limit(f"{_KEY_PREFIX}:auth:ip:{ip}", limit, 60)


def check_health_rate_limit(request: Request) -> None:
    """Rate-limit anonymous /health abuse; LB/VPC peers in operational.trusted_ips are exempt."""
    if not settings.API_RATE_LIMIT_ENFORCE:
        return
    if is_operational_access_allowed(request):
        return
    limit = int(settings.HEALTH_RATE_LIMIT_PER_MINUTE)
    if limit <= 0:
        return
    ip = _client_ip(request)
    _check_limit(f"{_KEY_PREFIX}:health:ip:{ip}", max(1, limit), 60)


def check_resource_create_rate_limit(principal: Principal) -> None:
    if not settings.API_RATE_LIMIT_ENFORCE:
        return
    burst_limit = max(1, int(settings.API_RESOURCE_CREATE_BURST))
    burst_window = max(1, int(settings.API_RESOURCE_CREATE_BURST_WINDOW_MINUTES)) * 60
    sustained_limit = max(1, int(settings.API_RESOURCE_CREATE_SUSTAINED_PER_MINUTE))
    org_limit = int(settings.API_RESOURCE_CREATE_ORG_PER_HOUR)

    if principal.user_id:
        user_key = f"{_KEY_PREFIX}:create:user:{principal.user_id}"
        _check_limit(user_key, burst_limit, burst_window)
        _check_limit(f"{user_key}:min", sustained_limit, 60)
    elif principal.api_key_id:
        key = f"{_KEY_PREFIX}:create:api_key:{principal.api_key_id}"
        _check_limit(key, burst_limit, burst_window)
        _check_limit(f"{key}:min", sustained_limit, 60)

    if org_limit > 0:
        org_key = f"{_KEY_PREFIX}:create:org:{principal.organization_id}"
        _check_limit(org_key, org_limit, 3600)


def enforce_auth_rate_limit(request: Request) -> None:
    check_auth_rate_limit(request)


def enforce_resource_create_rate_limit(
    principal: Principal = Depends(get_principal),
) -> Principal:
    check_resource_create_rate_limit(principal)
    return principal


def resource_create_limiter() -> Callable:
    return Depends(enforce_resource_create_rate_limit)
