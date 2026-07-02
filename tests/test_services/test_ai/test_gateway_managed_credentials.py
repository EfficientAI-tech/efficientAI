"""Tests for gateway-managed AI provider credentials."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.config import settings
from app.core.encryption import encrypt_api_key
from app.services.ai.llm_gateway import (
    GATEWAY_MANAGED_KEY_SENTINEL,
    gateway_managed_credentials_enabled,
    is_gateway_managed_stored_key,
    resolve_litellm_api_key,
)
from app.api.v1.routes import aiproviders as aiproviders_routes


def _sync_gateway_settings(**kwargs):
    settings.LLM_GATEWAY_PASSTHROUGH_PROVIDER_KEYS = kwargs.get("passthrough", True)
    settings.LLM_GATEWAY_ENABLED = kwargs.get("enabled", False)
    settings.LLM_GATEWAY_BASE_URL = kwargs.get("base_url")


@pytest.fixture(autouse=True)
def _reset_gateway_settings():
    original = (
        settings.LLM_GATEWAY_ENABLED,
        settings.LLM_GATEWAY_BASE_URL,
        settings.LLM_GATEWAY_PASSTHROUGH_PROVIDER_KEYS,
    )
    yield
    (
        settings.LLM_GATEWAY_ENABLED,
        settings.LLM_GATEWAY_BASE_URL,
        settings.LLM_GATEWAY_PASSTHROUGH_PROVIDER_KEYS,
    ) = original


def test_gateway_managed_credentials_enabled_when_passthrough_disabled():
    _sync_gateway_settings(passthrough=False)
    assert gateway_managed_credentials_enabled() is True


def test_is_gateway_managed_stored_key_detects_sentinel():
    encrypted = encrypt_api_key(GATEWAY_MANAGED_KEY_SENTINEL)
    assert is_gateway_managed_stored_key(encrypted) is True
    assert is_gateway_managed_stored_key(encrypt_api_key("sk-real")) is False


def test_resolve_litellm_api_key_returns_none_for_gateway_managed_credential():
    _sync_gateway_settings(
        enabled=True,
        base_url="http://localhost:8080/litellm",
        passthrough=False,
    )

    org_id = uuid4()
    provider = SimpleNamespace(
        provider="openai",
        api_key=encrypt_api_key(GATEWAY_MANAGED_KEY_SENTINEL),
    )
    db = SimpleNamespace(
        query=lambda *_args, **_kwargs: SimpleNamespace(
            filter=lambda *_a, **_k: SimpleNamespace(first=lambda: SimpleNamespace(bifrost_gateway_settings={}))
        )
    )

    assert resolve_litellm_api_key(org_id, db, provider) is None


def test_encrypt_provider_api_key_uses_sentinel_when_missing_and_gateway_managed():
    _sync_gateway_settings(passthrough=False)
    encrypted = aiproviders_routes._encrypt_provider_api_key(None)
    assert is_gateway_managed_stored_key(encrypted) is True


def test_encrypt_provider_api_key_requires_value_when_passthrough_enabled():
    _sync_gateway_settings(passthrough=True)
    with pytest.raises(HTTPException) as exc:
        aiproviders_routes._encrypt_provider_api_key(None)
    assert exc.value.status_code == 400
