"""
App-signed session tokens (HS256).

Used by the local-password provider to issue Bearer tokens after a successful
email/password login. Tokens are symmetrically signed with `settings.SECRET_KEY`
so they can be verified by any API/worker process that shares the secret.

Not used for external OIDC - that provider verifies upstream JWTs against
the IdP's JWKS directly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
from uuid import UUID, uuid4

from jose import JWTError, jwt

from app.config import settings

ISSUER = "efficientai-local"
ALGORITHM = "HS256"


def create_access_token(
    *,
    user_id: UUID,
    organization_id: UUID,
    email: str,
    session_epoch: int = 0,
    authenticated_org_ids: Optional[list[str]] = None,
    authenticated_org_epochs: Optional[dict[str, int]] = None,
    expires_in_minutes: Optional[int] = None,
) -> Tuple[str, str, int]:
    """Issue a short-lived Bearer token for the given user/org.

    Returns:
        Tuple of (encoded_token, jti, ttl_seconds).
    """
    ttl_minutes = expires_in_minutes or getattr(settings, "AUTH_LOCAL_TOKEN_TTL_MINUTES", 15)
    ttl_seconds = ttl_minutes * 60
    now = datetime.now(timezone.utc)
    jti = str(uuid4())
    payload: Dict[str, Any] = {
        "iss": ISSUER,
        "sub": str(user_id),
        "org_id": str(organization_id),
        "email": email,
        "session_epoch": int(session_epoch or 0),
        "authenticated_org_ids": authenticated_org_ids or [str(organization_id)],
        "authenticated_org_epochs": authenticated_org_epochs
        or {str(organization_id): int(session_epoch or 0)},
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ttl_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM), jti, ttl_seconds


def decode_access_token(token: str) -> Dict[str, Any]:
    """Verify a local access token and return its claims. Raises JWTError on failure."""
    try:
        return jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[ALGORITHM],
            issuer=ISSUER,
            options={"verify_aud": False},
        )
    except JWTError:
        # Re-raise so caller can distinguish from other errors.
        raise


def decode_access_token_allow_expired(token: str) -> Dict[str, Any]:
    """Verify signature/issuer but allow expired tokens (e.g. refresh org list)."""
    return jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[ALGORITHM],
        issuer=ISSUER,
        options={"verify_exp": False, "verify_aud": False},
    )
