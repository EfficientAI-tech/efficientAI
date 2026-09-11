"""
ReaderReadOnlyMiddleware
========================

Enforce a hard read-only boundary for callers whose org role is `reader`.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional

from fastapi import status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.config import settings
from app.core.auth.dependency import _resolve as _resolve_principal
from app.core.auth.rbac import get_org_role
from app.database import get_db
from app.models.database import RoleEnum

logger = logging.getLogger(__name__)

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _api_prefix() -> str:
    prefix = settings.API_V1_PREFIX or "/api/v1"
    return prefix.rstrip("/") + "/"


_READER_WRITE_ALLOWLIST: tuple[str, ...] = (
    "auth/login",
    "auth/signup",
    "auth/logout",
    "auth/refresh",
    "auth/password",
    "auth/switch-org",
    "auth/invitations/",
    "profile",
    "public-blind-test/",
)


def _path_after_prefix(path: str, prefix: str) -> Optional[str]:
    if not path.startswith(prefix):
        return None
    return path[len(prefix):]


def _is_allowlisted(remainder: str, allowlist: Iterable[str]) -> bool:
    for entry in allowlist:
        if remainder == entry.rstrip("/") or remainder.startswith(entry):
            return True
    return False


def _has_auth_credentials(request: Request) -> bool:
    if (
        request.headers.get("authorization")
        or request.headers.get("x-api-key")
        or request.headers.get("x-efficientai-api-key")
    ):
        return True
    if (
        request.query_params.get("token")
        or request.query_params.get("access_token")
        or request.query_params.get("api_key")
        or request.query_params.get("X-API-Key")
    ):
        return True
    if request.cookies.get("eai_access") or request.cookies.get("access_token") or request.cookies.get("api_key"):
        return True
    return False


class ReaderReadOnlyMiddleware(BaseHTTPMiddleware):
    """Block mutating API calls coming from a `reader`-role member."""

    async def dispatch(self, request: Request, call_next):
        if request.method.upper() not in _UNSAFE_METHODS:
            return await call_next(request)

        prefix = _api_prefix()
        remainder = _path_after_prefix(request.url.path, prefix)
        if remainder is None:
            return await call_next(request)

        if _is_allowlisted(remainder, _READER_WRITE_ALLOWLIST):
            return await call_next(request)

        if not _has_auth_credentials(request):
            return await call_next(request)

        authorization = request.headers.get("authorization")
        x_api_key = request.headers.get("x-api-key")
        x_eai_api_key = request.headers.get("x-efficientai-api-key")

        db_gen = get_db()
        db = next(db_gen)
        try:
            try:
                principal = _resolve_principal(
                    authorization,
                    x_api_key,
                    x_eai_api_key,
                    db,
                    request=request,
                )
            except Exception:
                return await call_next(request)

            if principal is None:
                return await call_next(request)

            role = get_org_role(principal, db)
        finally:
            try:
                next(db_gen, None)
            except Exception:
                pass

        if role == RoleEnum.READER:
            logger.info(
                "Blocked %s %s for reader user_id=%s org_id=%s",
                request.method,
                request.url.path,
                principal.user_id,
                principal.organization_id,
            )
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "detail": (
                        "Your account has the 'reader' role and cannot "
                        "create, update, or delete resources. Contact an "
                        "organization admin to request elevated access."
                    )
                },
            )

        return await call_next(request)
