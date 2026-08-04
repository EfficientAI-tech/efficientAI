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
    5. `access_token` cookie (fallback when no explicit query token)
    6. `api_key` / `X-API-Key` query param, then cookie (SSE / EventSource)
"""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

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


def _resolve(
    authorization: Optional[str],
    x_api_key: Optional[str],
    x_eai_api_key: Optional[str],
    db: Session,
    *,
    request: Optional[Request] = None,
) -> Optional[Principal]:
    bearer_token = _extract_bearer(authorization)
    api_key = x_api_key or x_eai_api_key or None

    if request is not None:
        query_bearer = (
            request.query_params.get("token")
            or request.query_params.get("access_token")
        )
        bearer_token = (
            bearer_token
            or query_bearer
            or request.cookies.get("access_token")
        )
        query_api_key = (
            request.query_params.get("api_key")
            or request.query_params.get("X-API-Key")
        )
        api_key = (
            api_key
            or query_api_key
            or request.cookies.get("api_key")
        )

    cred = RawCredential(
        bearer_token=bearer_token,
        api_key=api_key,
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
