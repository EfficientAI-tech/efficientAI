"""httpOnly session cookies for browser auth (Phase B)."""

from __future__ import annotations

import secrets
from typing import Optional

from starlette.requests import Request
from starlette.responses import Response

from app.config import settings

COOKIE_ACCESS = "eai_access"
COOKIE_REFRESH = "eai_refresh"
COOKIE_CSRF = "eai_csrf"
COOKIE_PLATFORM_ACCESS = "eai_platform_access"
LEGACY_ACCESS_COOKIE = "access_token"
CSRF_HEADER = "X-CSRF-Token"


def cookie_session_enabled() -> bool:
    return bool(getattr(settings, "AUTH_COOKIE_SESSION_ENABLED", True))


def _cookie_secure() -> bool:
    configured = getattr(settings, "AUTH_COOKIE_SECURE", None)
    if configured is not None:
        return bool(configured)
    return not settings.DEBUG


def _cookie_samesite() -> str:
    value = (getattr(settings, "AUTH_COOKIE_SAMESITE", None) or "lax").strip().lower()
    if value not in {"lax", "strict", "none"}:
        return "lax"
    return value


def _cookie_domain() -> Optional[str]:
    domain = getattr(settings, "AUTH_COOKIE_DOMAIN", None)
    if domain is None:
        return None
    stripped = str(domain).strip()
    return stripped or None


def _base_cookie_kwargs() -> dict:
    kwargs = {
        "httponly": True,
        "secure": _cookie_secure(),
        "samesite": _cookie_samesite(),
        "path": "/",
    }
    domain = _cookie_domain()
    if domain:
        kwargs["domain"] = domain
    return kwargs


def read_access_cookie(request: Request) -> Optional[str]:
    token = request.cookies.get(COOKIE_ACCESS) or request.cookies.get(LEGACY_ACCESS_COOKIE)
    if token and token.strip():
        return token.strip()
    return None


def read_refresh_cookie(request: Request) -> Optional[str]:
    token = request.cookies.get(COOKIE_REFRESH)
    if token and token.strip():
        return token.strip()
    return None


def read_csrf_cookie(request: Request) -> Optional[str]:
    token = request.cookies.get(COOKIE_CSRF)
    if token and token.strip():
        return token.strip()
    return None


def has_cookie_session(request: Request) -> bool:
    return read_access_cookie(request) is not None


def read_platform_access_cookie(request: Request) -> Optional[str]:
    token = request.cookies.get(COOKIE_PLATFORM_ACCESS)
    if token and token.strip():
        return token.strip()
    return None


def has_platform_cookie_session(request: Request) -> bool:
    return read_platform_access_cookie(request) is not None


def set_session_cookies(
    response: Response,
    *,
    access_token: str,
    refresh_token: Optional[str],
    access_ttl_seconds: int,
    refresh_ttl_seconds: int,
) -> str:
    """Set access, refresh, and CSRF cookies. Returns the CSRF token."""
    csrf_token = secrets.token_urlsafe(32)
    access_kwargs = {**_base_cookie_kwargs(), "max_age": max(1, int(access_ttl_seconds))}
    response.set_cookie(COOKIE_ACCESS, access_token, **access_kwargs)
    if refresh_token:
        refresh_kwargs = {**_base_cookie_kwargs(), "max_age": max(1, int(refresh_ttl_seconds))}
        response.set_cookie(COOKIE_REFRESH, refresh_token, **refresh_kwargs)
    csrf_kwargs = {
        "httponly": False,
        "secure": _cookie_secure(),
        "samesite": _cookie_samesite(),
        "path": "/",
        "max_age": max(1, int(refresh_ttl_seconds)),
    }
    domain = _cookie_domain()
    if domain:
        csrf_kwargs["domain"] = domain
    response.set_cookie(COOKIE_CSRF, csrf_token, **csrf_kwargs)
    return csrf_token


def clear_session_cookies(response: Response) -> None:
    clear_kwargs = {
        "path": "/",
        "secure": _cookie_secure(),
        "samesite": _cookie_samesite(),
    }
    domain = _cookie_domain()
    if domain:
        clear_kwargs["domain"] = domain
    for name in (COOKIE_ACCESS, COOKIE_REFRESH, COOKIE_CSRF, LEGACY_ACCESS_COOKIE):
        response.delete_cookie(name, **clear_kwargs)


def set_platform_session_cookies(
    response: Response,
    *,
    access_token: str,
    access_ttl_seconds: int,
) -> str:
    """Set platform admin access + CSRF cookies. Returns the CSRF token."""
    csrf_token = secrets.token_urlsafe(32)
    access_kwargs = {**_base_cookie_kwargs(), "max_age": max(1, int(access_ttl_seconds))}
    response.set_cookie(COOKIE_PLATFORM_ACCESS, access_token, **access_kwargs)
    csrf_kwargs = {
        "httponly": False,
        "secure": _cookie_secure(),
        "samesite": _cookie_samesite(),
        "path": "/",
        "max_age": max(1, int(access_ttl_seconds)),
    }
    domain = _cookie_domain()
    if domain:
        csrf_kwargs["domain"] = domain
    response.set_cookie(COOKIE_CSRF, csrf_token, **csrf_kwargs)
    return csrf_token


def clear_platform_session_cookies(response: Response) -> None:
    clear_kwargs = {
        "path": "/",
        "secure": _cookie_secure(),
        "samesite": _cookie_samesite(),
    }
    domain = _cookie_domain()
    if domain:
        clear_kwargs["domain"] = domain
    response.delete_cookie(COOKIE_PLATFORM_ACCESS, **clear_kwargs)
