"""HTTP security response headers."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import settings

_NO_STORE_CACHE = "no-cache, no-store, must-revalidate"
_ASSET_CACHE = "public, max-age=31536000, immutable"


def _apply_cache_control(request: Request, response: Response) -> None:
    if "cache-control" in response.headers:
        return

    path = request.url.path
    if path.startswith("/assets/"):
        response.headers["Cache-Control"] = _ASSET_CACHE
        return

    cache_value = _NO_STORE_CACHE
    if path.startswith("/api/"):
        cache_value = f"{_NO_STORE_CACHE}, private"

    response.headers["Cache-Control"] = cache_value
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"


def _apply_csp(response: Response) -> None:
    if not settings.CSP_ENABLED:
        return

    header_name = (
        "Content-Security-Policy-Report-Only"
        if settings.CSP_REPORT_ONLY
        else "Content-Security-Policy"
    )
    response.headers[header_name] = settings.CSP_POLICY


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add baseline security headers to every response."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        _apply_cache_control(request, response)
        _apply_csp(response)
        return response
