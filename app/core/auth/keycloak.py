"""
Keycloak provider (license-gated).

Verifies Bearer access tokens issued by a Keycloak realm. Turned on by:
    1. listing `keycloak` in `auth.providers`, AND
    2. an active enterprise license that includes `keycloak_sso`.

If step 1 is true but step 2 is not, the provider refuses to authenticate
with a clear error, and the user is pointed at the license page. This
matches the pattern used by other premium features in `app.dependencies`.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.core.auth.oidc_common import principal_from_oidc_claims, verify_jwt
from app.core.auth.principal import AuthMethod, Principal
from app.core.auth.providers import AuthError, AuthProvider, RawCredential
from app.core.license import has_auth_feature


class KeycloakProvider(AuthProvider):
    """Authenticates callers via a Keycloak-issued OIDC access token."""

    name = "keycloak"

    def accepts(self, cred: RawCredential) -> bool:
        if not cred.bearer_token:
            return False
        # Accept any bearer token here - the `local_password` provider is
        # registered first and claims its own tokens via the `iss` peek, so
        # anything still unclaimed at this point is fair game.
        return True

    def authenticate(self, cred: RawCredential, db: Session) -> Principal:
        if not cred.bearer_token:
            raise AuthError("Bearer token is required")

        if not has_auth_feature("keycloak_sso"):
            raise AuthError(
                "Keycloak SSO is an enterprise feature. "
                "Set EFFICIENTAI_LICENSE with a license that includes "
                "'keycloak_sso' to enable it.",
                status_code=403,
            )

        base = (settings.AUTH_KEYCLOAK_BASE_URL or "").rstrip("/")
        realm = settings.AUTH_KEYCLOAK_REALM
        audience = settings.AUTH_KEYCLOAK_AUDIENCE
        if not base or not realm:
            raise AuthError(
                "Keycloak is enabled but base_url/realm are not configured.",
                status_code=500,
            )

        issuer = f"{base}/realms/{realm}"
        jwks_uri = f"{issuer}/protocol/openid-connect/certs"

        claims = verify_jwt(
            cred.bearer_token,
            jwks_uri=jwks_uri,
            issuer=issuer,
            audience=audience,
        )

        org_claim_path: Optional[list] = settings.AUTH_KEYCLOAK_ORG_CLAIM_PATH or None

        return principal_from_oidc_claims(
            db,
            claims,
            auth_method=AuthMethod.KEYCLOAK,
            provider_name="keycloak",
            organization_claim_path=org_claim_path,
            default_organization_name=settings.AUTH_KEYCLOAK_DEFAULT_ORG_NAME,
        )
