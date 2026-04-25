"""
External OIDC provider (license-gated) for BYO IdPs like Okta, Azure AD,
Google Workspace, or Auth0.

Only activated when:
    1. `external_oidc` is listed in `auth.providers`, AND
    2. an active enterprise license includes `oidc_sso`.

Config shape (env vars all prefixed AUTH_OIDC_):
    issuer        - OIDC issuer URL (the provider publishes a .well-known doc there)
    audience      - expected `aud` claim; typically the client_id
    jwks_uri      - optional explicit JWKS endpoint; derived from the issuer if missing

The provider intentionally does not implement the auth code flow itself -
that happens in the frontend, which swaps the code for a Bearer token and then
calls our API with `Authorization: Bearer <token>`.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.core.auth.oidc_common import principal_from_oidc_claims, verify_jwt
from app.core.auth.principal import AuthMethod, Principal
from app.core.auth.providers import AuthError, AuthProvider, RawCredential
from app.core.license import has_auth_feature


class ExternalOIDCProvider(AuthProvider):
    """Authenticates callers via a Bearer token issued by a third-party IdP."""

    name = "external_oidc"

    def accepts(self, cred: RawCredential) -> bool:
        return bool(cred.bearer_token)

    def authenticate(self, cred: RawCredential, db: Session) -> Principal:
        if not cred.bearer_token:
            raise AuthError("Bearer token is required")

        if not has_auth_feature("oidc_sso"):
            raise AuthError(
                "External OIDC SSO is an enterprise feature. "
                "Set EFFICIENTAI_LICENSE with a license that includes "
                "'oidc_sso' to enable it.",
                status_code=403,
            )

        issuer = settings.AUTH_OIDC_ISSUER
        audience = settings.AUTH_OIDC_AUDIENCE
        jwks_uri = settings.AUTH_OIDC_JWKS_URI

        if not issuer:
            raise AuthError(
                "External OIDC is enabled but issuer is not configured.",
                status_code=500,
            )

        # Derive a sensible default JWKS URI when the operator didn't set one.
        if not jwks_uri:
            jwks_uri = issuer.rstrip("/") + "/.well-known/jwks.json"

        claims = verify_jwt(
            cred.bearer_token,
            jwks_uri=jwks_uri,
            issuer=issuer,
            audience=audience,
        )

        org_claim_path: Optional[list] = settings.AUTH_OIDC_ORG_CLAIM_PATH or None

        return principal_from_oidc_claims(
            db,
            claims,
            auth_method=AuthMethod.EXTERNAL_OIDC,
            provider_name="external_oidc",
            organization_claim_path=org_claim_path,
            default_organization_name=settings.AUTH_OIDC_DEFAULT_ORG_NAME,
        )
