"""
Unified authentication principal.

Every auth provider resolves the caller's credential into a `Principal`. Routes
never care which provider authenticated the caller - they only see the
resulting `Principal`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional
from uuid import UUID


class AuthMethod(str, Enum):
    """How the caller authenticated. Useful for audit logs and rate limiting."""

    API_KEY = "api_key"
    LOCAL_PASSWORD = "local_password"
    KEYCLOAK = "keycloak"
    EXTERNAL_OIDC = "external_oidc"


@dataclass(frozen=True)
class Principal:
    """
    The authenticated actor plus the org they are acting on behalf of.

    Fields:
        organization_id: The org the caller is scoped to. Always present.
        auth_method:     How the caller authenticated.
        user_id:         Set for all human auth methods and for API keys that
                         are bound to a user (the common case after first
                         login). May be None for legacy unbound API keys.
        api_key_id:      Set only when authenticated via an API key.
        email:           Email of the authenticated user when known.
        token_sub:       `sub` claim from the OIDC token when applicable.
    """

    organization_id: UUID
    auth_method: AuthMethod
    user_id: Optional[UUID] = None
    api_key_id: Optional[UUID] = None
    email: Optional[str] = None
    token_sub: Optional[str] = None

    @property
    def is_human(self) -> bool:
        """True when authenticated via an interactive login (not an API key)."""
        return self.auth_method != AuthMethod.API_KEY

    @property
    def is_machine(self) -> bool:
        """True when authenticated via an API key (programmatic access)."""
        return self.auth_method == AuthMethod.API_KEY
