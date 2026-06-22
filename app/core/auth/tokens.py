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
