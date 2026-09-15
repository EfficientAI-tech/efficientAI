"""Host header validation with load-balancer-friendly exemptions."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

from app.config import settings
from app.core.operational_access_middleware import _ip_in_trusted

_HEALTH_PATHS = {"/health", "/health/ready"}


def _normalize_path(path: str) -> str:
    return path.rstrip("/") or "/"


def _parse_host(request: Request) -> str | None:
    raw = request.headers.get("host")
    if not raw:
        return None
    raw = raw.strip()
    if raw.startswith("["):
        end = raw.find("]")
        if end == -1:
            return None
        return raw[1:end]
    if ":" in raw:
        return raw.split(":", 1)[0]
    return raw


def _matches_trusted_host(host: str, allowed_hosts: list[str]) -> bool:
    if "*" in allowed_hosts:
        return True
    for pattern in allowed_hosts:
        if host == pattern:
            return True
        if pattern.startswith("*.") and host.endswith(pattern[1:]):
            return True
    return False


def is_host_allowed(request: Request, allowed_hosts: list[str]) -> bool:
    if _normalize_path(request.url.path) in _HEALTH_PATHS:
        return True

    host = _parse_host(request)
    if host is None:
        return False

    if _matches_trusted_host(host, allowed_hosts):
        return True

    return _ip_in_trusted(host, settings.OPERATIONAL_TRUSTED_IPS)


class SelectiveTrustedHostMiddleware(BaseHTTPMiddleware):
    """Validate Host on API traffic; exempt /health and VPC IPs for LB probes."""

    def __init__(self, app, allowed_hosts: list[str]) -> None:
        super().__init__(app)
        self.allowed_hosts = allowed_hosts

    async def dispatch(self, request: Request, call_next) -> Response:
        if not is_host_allowed(request, self.allowed_hosts):
            return PlainTextResponse("Invalid host header", status_code=400)
        return await call_next(request)
