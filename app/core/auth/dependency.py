"""
FastAPI dependencies for the pluggable auth system.

Every authenticated route should depend on `get_principal`. Routes that need
the caller to be a human (not a machine with an API key) can additionally
depend on `get_user_principal`.

Credential resolution order (first match wins):
    1. `Authorization: Bearer <token>` header
    2. `X-API-Key` header
    3. `X-EFFICIENTAI-API-KEY` header (legacy, for webhooks)
    4. `token` / `access_token` query param (SSE / EventSource / <audio> src)
    5. `eai_access` / `access_token` cookie (httpOnly browser sessions)
    6. `api_key` / `X-API-Key` query param, then cookie (SSE / EventSource)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session
from starlette.websockets import WebSocket

from app.core.auth.cookies import COOKIE_ACCESS, LEGACY_ACCESS_COOKIE, read_access_cookie
from app.core.auth.principal import Principal
from app.core.auth.providers import AuthError, RawCredential, get_provider_registry
from app.database import get_db


def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


@dataclass(frozen=True)
class ResolvedCredentials:
    """Credentials plus where each value was read from (for URL vs cookie WS auth)."""

    credential: RawCredential
    bearer_source: Optional[str] = None  # header | query | cookie
    api_key_source: Optional[str] = None  # header | query | cookie


def resolve_request_credentials(
    *,
    authorization: Optional[str] = None,
    x_api_key: Optional[str] = None,
    x_eai_api_key: Optional[str] = None,
    request: Optional[Request] = None,
) -> RawCredential:
    """Collect bearer/API-key credentials from headers, query params, and cookies."""
    bearer_token = _extract_bearer(authorization)
    api_key = x_api_key or x_eai_api_key or None

    if request is not None:
        bearer_token = (
            bearer_token
            or request.query_params.get("token")
            or request.query_params.get("access_token")
            or read_access_cookie(request)
        )
        api_key = (
            api_key
            or request.query_params.get("api_key")
            or request.query_params.get("X-API-Key")
            or request.cookies.get("api_key")
        )

    return RawCredential(bearer_token=bearer_token, api_key=api_key)


def resolve_request_credentials_with_sources(
    *,
    authorization: Optional[str] = None,
    x_api_key: Optional[str] = None,
    x_eai_api_key: Optional[str] = None,
    request: Optional[Request] = None,
) -> ResolvedCredentials:
    """Resolve credentials and record whether each value came from header, query, or cookie."""
    bearer_source: Optional[str] = None
    api_key_source: Optional[str] = None

    bearer_token = _extract_bearer(authorization)
    if bearer_token:
        bearer_source = "header"
    api_key = x_api_key or x_eai_api_key or None
    if api_key:
        api_key_source = "header"

    if request is not None:
        if not bearer_token:
            query_bearer = (
                request.query_params.get("token")
                or request.query_params.get("access_token")
            )
            if query_bearer:
                bearer_token = query_bearer
                bearer_source = "query"
            else:
                cookie_bearer = read_access_cookie(request)
                if cookie_bearer:
                    bearer_token = cookie_bearer
                    bearer_source = "cookie"

        if not api_key:
            query_api_key = (
                request.query_params.get("api_key")
                or request.query_params.get("X-API-Key")
            )
            if query_api_key:
                api_key = query_api_key
                api_key_source = "query"
            else:
                cookie_api_key = request.cookies.get("api_key")
                if cookie_api_key:
                    api_key = cookie_api_key
                    api_key_source = "cookie"

    return ResolvedCredentials(
        credential=RawCredential(bearer_token=bearer_token, api_key=api_key),
        bearer_source=bearer_source,
        api_key_source=api_key_source,
    )


def resolve_websocket_credentials(websocket: WebSocket) -> RawCredential:
    """Collect bearer/API-key credentials from WebSocket query params and cookies."""
    bearer_token = (
        websocket.query_params.get("token")
        or websocket.query_params.get("access_token")
    )
    api_key = (
        websocket.query_params.get("X-API-Key")
        or websocket.query_params.get("api_key")
    )

    if not bearer_token:
        bearer_token = (
            websocket.cookies.get(COOKIE_ACCESS)
            or websocket.cookies.get(LEGACY_ACCESS_COOKIE)
        )
    if not api_key:
        api_key = websocket.cookies.get("api_key")

    if not bearer_token and not api_key:
        from urllib.parse import parse_qs

        raw_qs = websocket.scope.get("query_string", b"")
        if isinstance(raw_qs, bytes):
            raw_qs = raw_qs.decode("utf-8", errors="replace")
        parsed = parse_qs(raw_qs)
        bearer_token = bearer_token or (parsed.get("token") or parsed.get("access_token") or [None])[0]
        api_key = api_key or (parsed.get("X-API-Key") or parsed.get("api_key") or [None])[0]

    return RawCredential(bearer_token=bearer_token, api_key=api_key)


def _resolve(
    authorization: Optional[str],
    x_api_key: Optional[str],
    x_eai_api_key: Optional[str],
    db: Session,
    *,
    request: Optional[Request] = None,
) -> Optional[Principal]:
    cred = resolve_request_credentials(
        authorization=authorization,
        x_api_key=x_api_key,
        x_eai_api_key=x_eai_api_key,
        request=request,
    )
    if not cred.bearer_token and not cred.api_key:
        return None

    registry = get_provider_registry()
    provider = registry.find(cred)
    if provider is None:
        return None

    try:
        return provider.authenticate(cred, db)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


def get_principal(
    request: Request,
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    x_eai_api_key: Optional[str] = Header(None, alias="X-EFFICIENTAI-API-KEY"),
    db: Session = Depends(get_db),
) -> Principal:
    """Require an authenticated caller via any enabled provider."""
    principal = _resolve(authorization, x_api_key, x_eai_api_key, db, request=request)
    if principal is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required (send Authorization: Bearer ... or X-API-Key)",
        )
    return principal


def get_optional_principal(
    request: Request,
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    x_eai_api_key: Optional[str] = Header(None, alias="X-EFFICIENTAI-API-KEY"),
    db: Session = Depends(get_db),
) -> Optional[Principal]:
    """Return a Principal if the caller provided valid credentials, else None."""
    return _resolve(authorization, x_api_key, x_eai_api_key, db, request=request)


def get_user_principal(principal: Principal = Depends(get_principal)) -> Principal:
    """Require a human-backed principal (rejects anonymous API keys)."""
    if principal.user_id is None:
        raise HTTPException(
            status_code=403,
            detail="This endpoint requires a user-backed credential, not a machine API key.",
        )
    return principal
