"""Restrict operational endpoints (/health, /metrics) from the public internet."""

from __future__ import annotations

import ipaddress
import logging
from typing import Iterable

from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import settings
from app.core.auth.dependency import _resolve
from app.database import SessionLocal

logger = logging.getLogger(__name__)

_PROBE_USER_AGENTS = ("ELB-HealthChecker", "kube-probe")
_HEALTH_PATH = "/health"
_METRICS_PREFIX = "/metrics"


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def _ip_in_trusted(ip: str, trusted: Iterable[str]) -> bool:
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False

    for entry in trusted:
        entry = entry.strip()
        if not entry:
            continue
        try:
            if "/" in entry:
                if address in ipaddress.ip_network(entry, strict=False):
                    return True
            elif address == ipaddress.ip_address(entry):
                return True
        except ValueError:
            logger.warning("Ignoring invalid operational trusted IP entry: %s", entry)
    return False


def _has_authenticated_caller(request: Request) -> bool:
    db = SessionLocal()
    try:
        principal = _resolve(
            request.headers.get("authorization"),
            request.headers.get("x-api-key"),
            request.headers.get("x-efficientai-api-key"),
            db,
        )
        return principal is not None
    except HTTPException:
        return False
    finally:
        db.close()


def _is_health_probe(request: Request) -> bool:
    user_agent = request.headers.get("user-agent", "")
    if any(marker in user_agent for marker in _PROBE_USER_AGENTS):
        return True

    if request.headers.get("x-forwarded-for"):
        return False

    direct_ip = request.client.host if request.client else None
    if direct_ip and _ip_in_trusted(direct_ip, settings.OPERATIONAL_TRUSTED_IPS):
        return True
    return False


def is_operational_access_allowed(request: Request) -> bool:
    """Return True when the caller may access a protected operational endpoint."""
    if settings.OPERATIONAL_PUBLIC:
        return True

    path = request.url.path
    if path == _HEALTH_PATH and _is_health_probe(request):
        return True

    client_ip = _client_ip(request)
    if client_ip and _ip_in_trusted(client_ip, settings.OPERATIONAL_TRUSTED_IPS):
        return True

    if _has_authenticated_caller(request):
        return True

    return False


def is_operational_path(path: str) -> bool:
    return path == _HEALTH_PATH or path.startswith(_METRICS_PREFIX)


class OperationalAccessMiddleware(BaseHTTPMiddleware):
    """Block anonymous public access to /health and /metrics."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if is_operational_path(request.url.path) and not is_operational_access_allowed(request):
            return JSONResponse(status_code=404, content={"detail": "Not found"})

        return await call_next(request)
