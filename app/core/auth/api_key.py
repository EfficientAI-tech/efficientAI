"""
API key provider.

Wraps the existing `app.core.security.verify_api_key` lookup into the new
`AuthProvider` protocol. Always enabled in every deployment tier - this is the
one credential class the SDK, webhooks, and machine integrations rely on.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.auth.principal import AuthMethod, Principal
from app.core.auth.providers import AuthError, AuthProvider, RawCredential
from app.models.database import APIKey


class ApiKeyProvider(AuthProvider):
    """Authenticates callers via a database-backed API key."""

    name = "api_key"

    def accepts(self, cred: RawCredential) -> bool:
        return bool(cred.api_key)

    def authenticate(self, cred: RawCredential, db: Session) -> Principal:
        if not cred.api_key:
            raise AuthError("API key is required")

        db_key = (
            db.query(APIKey)
            .filter(APIKey.key == cred.api_key, APIKey.is_active == True)  # noqa: E712
            .first()
        )
        if not db_key:
            raise AuthError("Invalid API key")

        db_key.last_used = datetime.now(timezone.utc)
        db.commit()

        return Principal(
            organization_id=db_key.organization_id,
            auth_method=AuthMethod.API_KEY,
            user_id=db_key.user_id,
            api_key_id=db_key.id,
        )
