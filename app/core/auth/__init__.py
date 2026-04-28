"""
Pluggable authentication for EfficientAI.

This package exposes one unified `Principal` type and a single `get_principal`
FastAPI dependency that accepts credentials from any of the enabled providers:

    - api_key         (always available, backward compatible)
    - local_password  (email+password, app-signed JWT, OSS default human login)
    - external_oidc   (license-gated: BYO IdP such as Okta, Azure AD,
                      Google Workspace, AWS Cognito, Auth0, Ping, etc.)

Configured via `auth.providers` in `config.yml`. Providers not listed there are
disabled - even if a license would otherwise enable them. Providers that ARE
listed but require a license feature are still rejected if the license is
missing that feature (see `app.core.license.has_auth_feature`).
"""

from app.core.auth.principal import AuthMethod, Principal
from app.core.auth.providers import (
    AuthError,
    ProviderRegistry,
    get_provider_registry,
)
from app.core.auth.dependency import (
    get_principal,
    get_optional_principal,
    get_user_principal,
)

__all__ = [
    "AuthMethod",
    "Principal",
    "AuthError",
    "ProviderRegistry",
    "get_provider_registry",
    "get_principal",
    "get_optional_principal",
    "get_user_principal",
]
