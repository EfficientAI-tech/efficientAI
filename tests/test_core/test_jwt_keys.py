"""Production auth configuration guards (trusted hosts, etc.)."""

import pytest

from app.config import settings, validate_auth_configuration


def test_validate_auth_requires_trusted_hosts_when_not_debug(monkeypatch):
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "SECRET_KEY", "x" * 32)
    monkeypatch.setattr(settings, "FRONTEND_BASE_URL", "https://app.example.com")
    monkeypatch.setattr(settings, "TRUSTED_HOSTS", [])
    monkeypatch.setattr(settings, "TRUSTED_HOSTS_AUTO_FROM_FRONTEND", False)
    monkeypatch.setattr(settings, "TRUSTED_HOSTS_EXPLICIT", [])
    monkeypatch.setattr(settings, "TRUSTED_HOSTS_FROM_ENV", [])
    monkeypatch.setattr(settings, "AUTH_PROVIDERS", ["api_key"])

    with pytest.raises(RuntimeError, match="TRUSTED_HOSTS"):
        validate_auth_configuration()
