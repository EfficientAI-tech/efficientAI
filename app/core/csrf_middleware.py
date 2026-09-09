"""CSRF protection for cookie-based browser sessions."""

from __future__ import annotations

import logging

from fastapi import status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.config import settings
from app.core.auth.cookies import (
    CSRF_HEADER,
    cookie_session_enabled,
    has_cookie_session,
    read_csrf_cookie,
)

logger = logging.getLogger(__name__)

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

_CSRF_EXEMPT_SUFFIXES = (
    "auth/login",
    "auth/signup",
    "auth/refresh",
    "auth/oidc/session",
    "auth/config",
    "auth/invitations/preview/",
    "telephony/",
    "public-blind-test/",
)


def _api_prefix() -> str:
    prefix = settings.API_V1_PREFIX or "/api/v1"
    return prefix.rstrip("/") + "/"


def _path_after_prefix(path: str, prefix: str) -> str | None:
    if not path.startswith(prefix):
        return None
    return path[len(prefix) :]


def _is_csrf_exempt(remainder: str) -> bool:
    for entry in _CSRF_EXEMPT_SUFFIXES:
        if remainder == entry.rstrip("/") or remainder.startswith(entry):
            return True
    return False


def _has_machine_api_key_header(request: Request) -> bool:
    return bool(
        request.headers.get("x-api-key")
        or request.headers.get("x-efficientai-api-key")
    )


class CsrfMiddleware(BaseHTTPMiddleware):
    """Require double-submit CSRF token for mutating cookie-authenticated requests."""

    async def dispatch(self, request: Request, call_next):
        if not cookie_session_enabled():
            return await call_next(request)

        if request.method.upper() not in _UNSAFE_METHODS:
            return await call_next(request)

        if not has_cookie_session(request):
            return await call_next(request)

        if _has_machine_api_key_header(request):
            return await call_next(request)

        prefix = _api_prefix()
        remainder = _path_after_prefix(request.url.path, prefix)
        if remainder is not None and _is_csrf_exempt(remainder):
            return await call_next(request)

        expected = read_csrf_cookie(request)
        provided = request.headers.get(CSRF_HEADER) or request.headers.get("X-Csrf-Token")
        if not expected or not provided or provided != expected:
            logger.info(
                "Blocked %s %s due to missing or invalid CSRF token",
                request.method,
                request.url.path,
            )
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"detail": "CSRF token missing or invalid"},
            )

        return await call_next(request)
