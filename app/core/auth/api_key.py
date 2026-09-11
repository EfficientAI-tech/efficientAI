"""
API key provider.

Wraps the existing `app.core.security.verify_api_key` lookup into the new
`AuthProvider` protocol. Always enabled in every deployment tier - this is the
one credential class the SDK, webhooks, and machine integrations rely on.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import redis
from sqlalchemy.orm import Session

from app.config import settings
from app.core.auth.org_access import ensure_organization_active
from app.core.auth.principal import AuthMethod, Principal
from app.core.auth.providers import AuthError, AuthProvider, RawCredential
from app.models.database import APIKey

_redis_client: Optional[redis.Redis] = None


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def _cache_key(api_key: str) -> str:
    digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    return f"auth:api_key:{digest}"


def _read_api_key_cache(api_key: str) -> Optional[Principal]:
    try:
        raw = _get_redis().get(_cache_key(api_key))
    except redis.RedisError:
        return None
    if not raw:
        return None
    try:
        payload = json.loads(raw)
        return Principal(
            organization_id=UUID(payload["organization_id"]),
            auth_method=AuthMethod.API_KEY,
            user_id=UUID(payload["user_id"]) if payload.get("user_id") else None,
            api_key_id=UUID(payload["api_key_id"]) if payload.get("api_key_id") else None,
        )
    except (TypeError, KeyError, json.JSONDecodeError):
        return None


def _write_api_key_cache(api_key: str, principal: Principal) -> None:
    ttl = max(30, int(settings.TRACES_API_KEY_CACHE_TTL_SECONDS))
    payload = {
        "organization_id": str(principal.organization_id),
        "user_id": str(principal.user_id) if principal.user_id else None,
        "api_key_id": str(principal.api_key_id) if principal.api_key_id else None,
    }
    try:
        _get_redis().setex(_cache_key(api_key), ttl, json.dumps(payload))
    except redis.RedisError:
        return


class ApiKeyProvider(AuthProvider):
    """Authenticates callers via a database-backed API key."""

    name = "api_key"

    def accepts(self, cred: RawCredential) -> bool:
        return bool(cred.api_key)

    def authenticate(self, cred: RawCredential, db: Session) -> Principal:
        if not cred.api_key:
            raise AuthError("API key is required")

        cached = _read_api_key_cache(cred.api_key)
        if cached is not None:
            return cached

        db_key = (
            db.query(APIKey)
            .filter(APIKey.key == cred.api_key, APIKey.is_active == True)  # noqa: E712
            .first()
        )
        if not db_key:
            raise AuthError("Invalid API key")

        ensure_organization_active(db, db_key.organization_id)

        now = datetime.now(timezone.utc)
        last = db_key.last_used
        if last is not None:
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if (now - last).total_seconds() <= 60:
                return Principal(
                    organization_id=db_key.organization_id,
                    auth_method=AuthMethod.API_KEY,
                    user_id=db_key.user_id,
                    api_key_id=db_key.id,
                )

        db_key.last_used = now
        db.commit()

        principal = Principal(
            organization_id=db_key.organization_id,
            auth_method=AuthMethod.API_KEY,
            user_id=db_key.user_id,
            api_key_id=db_key.id,
        )
        _write_api_key_cache(cred.api_key, principal)
        return principal
