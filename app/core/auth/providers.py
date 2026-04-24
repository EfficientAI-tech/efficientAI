"""
Auth provider protocol and registry.

A provider is anything that can turn a raw HTTP credential (header, cookie,
query param) into a `Principal`. Providers declare which credential they
consume; `get_principal` walks the registry and picks the first one whose
credential is present.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Protocol, runtime_checkable

from sqlalchemy.orm import Session

from app.core.auth.principal import Principal


class AuthError(Exception):
    """Raised when a provider detects a present-but-invalid credential."""

    def __init__(self, message: str, status_code: int = 401):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class RawCredential:
    """
    Credential material extracted from the incoming HTTP request.

    Providers inspect the fields they care about. Exactly one of `bearer_token`
    or `api_key` is typically set by the dependency before providers run.
    """

    bearer_token: Optional[str] = None
    api_key: Optional[str] = None


@runtime_checkable
class AuthProvider(Protocol):
    """Contract every auth provider must satisfy."""

    name: str

    def accepts(self, cred: RawCredential) -> bool:
        """Return True if this provider can consume the given credential."""
        ...

    def authenticate(self, cred: RawCredential, db: Session) -> Principal:
        """
        Verify the credential and return a Principal.

        Raises:
            AuthError: if the credential is invalid, expired, or the provider
                is enabled by config but disabled by the current license.
        """
        ...


class ProviderRegistry:
    """
    Holds the list of enabled auth providers in priority order.

    The registry is built once at import time from `settings.AUTH_PROVIDERS`
    and survives the life of the process. Providers whose license feature is
    not enabled will raise AuthError on `authenticate`, not on registration -
    this keeps hot-reload of the license file possible without restarting.
    """

    def __init__(self, providers: List[AuthProvider]):
        self._providers = providers

    @property
    def providers(self) -> List[AuthProvider]:
        return list(self._providers)

    def find(self, cred: RawCredential) -> Optional[AuthProvider]:
        """Return the first provider that accepts this credential, if any."""
        for p in self._providers:
            if p.accepts(cred):
                return p
        return None

    def names(self) -> List[str]:
        return [p.name for p in self._providers]


_registry_singleton: Optional[ProviderRegistry] = None


def get_provider_registry() -> ProviderRegistry:
    """
    Lazily construct and cache the provider registry from app settings.

    Import order matters: we do the actual construction here (not at module
    import time) so that config.yml values loaded by `load_config_from_file`
    at startup are visible.
    """
    global _registry_singleton
    if _registry_singleton is not None:
        return _registry_singleton

    from app.config import settings
    from app.core.auth.api_key import ApiKeyProvider
    from app.core.auth.local import LocalPasswordProvider
    from app.core.auth.external_oidc import ExternalOIDCProvider

    enabled = {p.strip().lower() for p in (settings.AUTH_PROVIDERS or []) if p}
    if not enabled:
        enabled = {"api_key"}

    # Fixed priority order: API keys first (deterministic machine path), then
    # the local-password bearer (which self-identifies by its `iss` claim),
    # then external OIDC which consumes any remaining bearer token.
    ordered = [
        ("api_key", ApiKeyProvider),
        ("local_password", LocalPasswordProvider),
        ("external_oidc", ExternalOIDCProvider),
    ]

    providers: List[AuthProvider] = []
    for name, builder in ordered:
        if name in enabled:
            providers.append(builder())

    _registry_singleton = ProviderRegistry(providers)
    return _registry_singleton


def reset_provider_registry() -> None:
    """Drop the cached registry. Useful for tests and hot reload."""
    global _registry_singleton
    _registry_singleton = None
