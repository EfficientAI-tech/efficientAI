"""
ReaderReadOnlyMiddleware
========================

Enforce a hard read-only boundary for callers whose org role is `reader`.

Why a middleware: per-route role guards have to be added one-by-one and missed
guards become silent privilege-escalation bugs. A middleware gives us a
single, auditable choke point that turns *any* mutating request from a reader
into a 403 - even on routes added later that forgot to wire up the dependency.

Behavior
--------
- Only inspects requests under the API prefix (`/api/v1/`).
- Only inspects unsafe HTTP methods (`POST`, `PUT`, `PATCH`, `DELETE`).
- Skips public/unauthenticated routes (login, signup, OIDC callback,
  public blind-test form).
- Skips a small allowlist of self-service routes that every member - including
  readers - must be able to call (logout, accept/decline an invitation, change
  their own password, update their own profile/preferences).
- Resolves the caller's role using the same auth providers as `get_principal`
  so this stays consistent with the rest of the app.

If the caller is not authenticated at all, we let the request flow through so
the existing per-route auth dependency can produce its standard 401 - we
don't want this middleware to mask auth errors with 403s.
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


# Methods that mutate state. GET / HEAD / OPTIONS are always allowed.
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _api_prefix() -> str:
    # `settings.API_V1_PREFIX` is e.g. `/api/v1`. Make sure it has a trailing
    # slash for safe `startswith` matching so `/api/v1foo` doesn't match
    # `/api/v1`.
    prefix = settings.API_V1_PREFIX or "/api/v1"
    return prefix.rstrip("/") + "/"


# Paths under the API prefix that even a reader is allowed to POST/PUT/PATCH/DELETE
# against. Match is "starts with" against the path *after* the API prefix.
#
# Keep this list tight: anything you put here is a write a reader can perform.
_READER_WRITE_ALLOWLIST: tuple[str, ...] = (
    # Auth: login, signup, logout, validate, switch own org, update own
    # password. Access to these doesn't grant write access to org resources.
    "auth/",
    # Profile: own profile, own preferences, accept/decline invitations.
    "profile",
    # Public, unauthenticated blind-test submissions (rater UI). Auth is via
    # an unguessable share_token in the body, not a Bearer token.
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


class ReaderReadOnlyMiddleware(BaseHTTPMiddleware):
    """Block mutating API calls coming from a `reader`-role member."""

    async def dispatch(self, request: Request, call_next):
        # Fast path: only care about mutating methods on the API.
        if request.method.upper() not in _UNSAFE_METHODS:
            return await call_next(request)

        prefix = _api_prefix()
        remainder = _path_after_prefix(request.url.path, prefix)
        if remainder is None:
            return await call_next(request)

        # Self-service / public writes are always allowed.
        if _is_allowlisted(remainder, _READER_WRITE_ALLOWLIST):
            return await call_next(request)

        # Pull credentials from the same headers the auth dependency reads.
        authorization = request.headers.get("authorization")
        x_api_key = request.headers.get("x-api-key")
        x_eai_api_key = request.headers.get("x-efficientai-api-key")

        if not authorization and not x_api_key and not x_eai_api_key:
            # Unauthenticated - let the route's own auth dep produce a 401.
            return await call_next(request)

        # Open a short-lived DB session just for the role lookup. The auth
        # providers and the role query are read-only, so this doesn't fight
        # the request's own session.
        db_gen = get_db()
        db = next(db_gen)
        try:
            try:
                principal = _resolve_principal(
                    authorization, x_api_key, x_eai_api_key, db
                )
            except Exception:
                # If credential resolution itself raised (bad token, etc.),
                # fall through and let the route's auth dep produce the
                # standard error response.
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
