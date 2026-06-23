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

_HEALTH_PATH = "/health"
_METRICS_PREFIX = "/metrics"


def _peer_ip(request: Request) -> str | None:
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


def _resolved_trusted_ip(request: Request) -> str | None:
    """Resolve the client IP that may be matched against OPERATIONAL_TRUSTED_IPS.

    - Direct connections (no X-Forwarded-For): use the TCP peer address. This
      covers ALB/kube health checks that connect from a VPC address.
    - Proxied connections: only honor X-Forwarded-For when the TCP peer is
      itself in the trusted list (known load balancer). Use the rightmost hop,
      which is the address appended by that proxy — not the leftmost hop, which
      can be client-supplied and spoofed.
    """
    peer = _peer_ip(request)
    if peer is None:
        return None

    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        return peer

    if not _ip_in_trusted(peer, settings.OPERATIONAL_TRUSTED_IPS):
        return None

    hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
    if not hops:
        return peer
    return hops[-1]


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


def is_operational_access_allowed(request: Request) -> bool:
    """Return True when the caller may access a protected operational endpoint."""
    if settings.OPERATIONAL_PUBLIC:
        return True

    resolved_ip = _resolved_trusted_ip(request)
    if resolved_ip and _ip_in_trusted(resolved_ip, settings.OPERATIONAL_TRUSTED_IPS):
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
