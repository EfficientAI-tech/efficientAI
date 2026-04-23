"""
Local email/password provider.

Verifies app-signed JWTs minted by the `/auth/login` endpoint. The login
endpoint itself lives in `app.api.v1.routes.auth` and uses
`app.core.password.verify_password` for the bcrypt check.

Enabled by listing `local_password` in `auth.providers` in config.yml. No
license check - this is available in OSS to give self-hosters a way to log in
without Keycloak.
"""

from __future__ import annotations

from uuid import UUID

from jose import JWTError
from sqlalchemy.orm import Session

from app.core.auth.principal import AuthMethod, Principal
from app.core.auth.providers import AuthError, AuthProvider, RawCredential
from app.core.auth.tokens import ISSUER, decode_access_token


class LocalPasswordProvider(AuthProvider):
    """Verifies Bearer tokens issued by the local /auth/login endpoint."""

    name = "local_password"

    def accepts(self, cred: RawCredential) -> bool:
        if not cred.bearer_token:
            return False
        # Only claim this token if it was minted by us. We peek at the
        # unverified issuer claim; integrity is checked below.
        try:
            from jose import jwt as jose_jwt
            unverified = jose_jwt.get_unverified_claims(cred.bearer_token)
            return unverified.get("iss") == ISSUER
        except Exception:
            return False

    def authenticate(self, cred: RawCredential, db: Session) -> Principal:
        if not cred.bearer_token:
            raise AuthError("Bearer token is required")

        try:
            claims = decode_access_token(cred.bearer_token)
        except JWTError as e:
            raise AuthError(f"Invalid token: {e}")

        try:
            user_id = UUID(claims["sub"])
            org_id = UUID(claims["org_id"])
        except (KeyError, ValueError) as e:
            raise AuthError(f"Malformed token: {e}")

        # Confirm the user still exists and is active.
        from app.models.database import OrganizationMember, User

        user = db.query(User).filter(User.id == user_id, User.is_active == True).first()  # noqa: E712
        if not user:
            raise AuthError("User no longer active")

        member = (
            db.query(OrganizationMember)
            .filter(
                OrganizationMember.user_id == user_id,
                OrganizationMember.organization_id == org_id,
            )
            .first()
        )
        if not member:
            raise AuthError("User is not a member of this organization")

        return Principal(
            organization_id=org_id,
            auth_method=AuthMethod.LOCAL_PASSWORD,
            user_id=user_id,
            email=claims.get("email") or user.email,
            token_sub=claims.get("sub"),
        )
