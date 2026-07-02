"""Tests for multi-gateway LLM resolver (Bifrost + LiteLLM Proxy)."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.config import settings
from app.services.ai import llm_gateway as gateway_module
from app.services.ai.llm_gateway import (
    apply_llm_gateway,
    LITELLM_GATEWAY_PLACEHOLDER_API_KEY,
    resolve_llm_gateway,
)


def _set_platform_gateway(
    *,
    enabled=False,
    gateway_type="bifrost",
    base_url=None,
    virtual_key=None,
    master_key=None,
    passthrough=True,
):
    settings.LLM_GATEWAY_ENABLED = enabled
    settings.LLM_GATEWAY_TYPE = gateway_type
    settings.LLM_GATEWAY_BASE_URL = base_url
    settings.LLM_GATEWAY_VIRTUAL_KEY = virtual_key
    settings.LLM_GATEWAY_MASTER_KEY = master_key
    settings.LLM_GATEWAY_PASSTHROUGH_PROVIDER_KEYS = passthrough


@pytest.fixture(autouse=True)
def _reset_gateway_settings():
    original = (
        settings.LLM_GATEWAY_ENABLED,
        settings.LLM_GATEWAY_TYPE,
        settings.LLM_GATEWAY_BASE_URL,
        settings.LLM_GATEWAY_VIRTUAL_KEY,
        settings.LLM_GATEWAY_MASTER_KEY,
        settings.LLM_GATEWAY_PASSTHROUGH_PROVIDER_KEYS,
    )
    yield
    (
        settings.LLM_GATEWAY_ENABLED,
        settings.LLM_GATEWAY_TYPE,
        settings.LLM_GATEWAY_BASE_URL,
        settings.LLM_GATEWAY_VIRTUAL_KEY,
        settings.LLM_GATEWAY_MASTER_KEY,
        settings.LLM_GATEWAY_PASSTHROUGH_PROVIDER_KEYS,
    ) = original


def _org_db(org_settings=None):
    org_id = uuid4()
    org = SimpleNamespace(
        id=org_id,
        llm_gateway_settings=org_settings,
    )

    class _Query:
        def filter(self, *_args, **_kwargs):
            return self

        def first(self):
            return org

    db = SimpleNamespace(query=lambda *_args, **_kwargs: _Query())
    return org_id, db


def test_resolve_returns_none_when_platform_and_org_disabled():
    _set_platform_gateway(enabled=False)
    org_id, db = _org_db({"enabled": None})
    assert resolve_llm_gateway(org_id, db) is None


def test_resolve_bifrost_uses_platform_defaults():
    _set_platform_gateway(
        enabled=True,
        base_url="http://bifrost.example.com/litellm",
        virtual_key="platform-vk",
    )
    org_id, db = _org_db({"enabled": None})
    config = resolve_llm_gateway(org_id, db)

    assert config is not None
    assert config.gateway_type == "bifrost"
    assert config.api_base == "http://bifrost.example.com/litellm"
    assert config.virtual_key == "platform-vk"


def test_org_opt_out_overrides_platform():
    _set_platform_gateway(enabled=True, base_url="http://bifrost.example.com/litellm")
    org_id, db = _org_db({"enabled": False})
    assert resolve_llm_gateway(org_id, db) is None


def test_org_override_url_and_virtual_key(monkeypatch):
    _set_platform_gateway(enabled=False)
    org_id, db = _org_db(
        {
            "enabled": True,
            "gateway_type": "bifrost",
            "base_url": "http://customer-bifrost:9090/litellm",
            "virtual_key": "encrypted-vk",
        }
    )
    monkeypatch.setattr(
        gateway_module,
        "_decrypt_org_virtual_key",
        lambda _raw: "org-vk",
    )

    config = resolve_llm_gateway(org_id, db)

    assert config is not None
    assert config.gateway_type == "bifrost"
    assert config.api_base == "http://customer-bifrost:9090/litellm"
    assert config.virtual_key == "org-vk"


def test_legacy_org_json_without_gateway_type_defaults_to_bifrost():
    _set_platform_gateway(enabled=True, base_url="http://bifrost.example.com/litellm")
    org_id, db = _org_db({"enabled": True})
    config = resolve_llm_gateway(org_id, db)
    assert config is not None
    assert config.gateway_type == "bifrost"


def test_resolve_litellm_proxy_uses_platform_defaults():
    _set_platform_gateway(
        enabled=True,
        gateway_type="litellm_proxy",
        base_url="http://proxy.example.com:4000",
        master_key="platform-master",
    )
    org_id, db = _org_db({"enabled": None})
    config = resolve_llm_gateway(org_id, db)

    assert config is not None
    assert config.gateway_type == "litellm_proxy"
    assert config.api_base == "http://proxy.example.com:4000"
    assert config.master_key == "platform-master"


def test_org_gateway_type_overrides_platform_type():
    _set_platform_gateway(
        enabled=True,
        gateway_type="bifrost",
        base_url="http://bifrost.example.com/litellm",
    )
    org_id, db = _org_db(
        {
            "enabled": True,
            "gateway_type": "litellm_proxy",
            "base_url": "http://org-proxy:4000",
        }
    )
    config = resolve_llm_gateway(org_id, db)
    assert config is not None
    assert config.gateway_type == "litellm_proxy"
    assert config.api_base == "http://org-proxy:4000"


def test_apply_bifrost_gateway_injects_placeholder_api_key_when_gateway_managed():
    _set_platform_gateway(
        enabled=True,
        base_url="http://localhost:8080/litellm",
        passthrough=False,
    )
    org_id, db = _org_db({"enabled": True})
    result = apply_llm_gateway(
        {"model": "openai/gpt-4o-mini", "messages": []},
        organization_id=org_id,
        db=db,
    )

    assert result["api_base"] == "http://localhost:8080/litellm"
    assert result["api_key"] == LITELLM_GATEWAY_PLACEHOLDER_API_KEY


def test_apply_bifrost_gateway_injects_api_base_and_headers():
    _set_platform_gateway(
        enabled=True,
        base_url="http://localhost:8080/litellm",
        virtual_key="vk-123",
    )
    org_id, db = _org_db({"enabled": True})
    result = apply_llm_gateway(
        {"model": "openai/gpt-4o-mini", "api_key": "sk-test", "messages": []},
        organization_id=org_id,
        db=db,
    )

    assert result["api_base"] == "http://localhost:8080/litellm"
    assert result["extra_headers"]["x-bf-vk"] == "vk-123"
    assert result["api_key"] == "sk-test"


def test_apply_litellm_proxy_injects_master_key_when_not_passthrough():
    _set_platform_gateway(
        enabled=True,
        gateway_type="litellm_proxy",
        base_url="http://localhost:4000",
        master_key="proxy-master",
        passthrough=False,
    )
    org_id, db = _org_db({"enabled": True})
    result = apply_llm_gateway(
        {"model": "openai/gpt-4o-mini", "api_key": "sk-test", "messages": []},
        organization_id=org_id,
        db=db,
    )

    assert result["api_base"] == "http://localhost:4000"
    assert result["api_key"] == "proxy-master"


def test_apply_litellm_proxy_keeps_org_key_when_passthrough():
    _set_platform_gateway(
        enabled=True,
        gateway_type="litellm_proxy",
        base_url="http://localhost:4000",
        master_key="proxy-master",
        passthrough=True,
    )
    org_id, db = _org_db({"enabled": True})
    result = apply_llm_gateway(
        {"model": "openai/gpt-4o-mini", "api_key": "sk-test", "messages": []},
        organization_id=org_id,
        db=db,
    )

    assert result["api_base"] == "http://localhost:4000"
    assert result["api_key"] == "sk-test"


def test_apply_bifrost_gateway_forces_openai_compatible_routing_for_gemini():
    _set_platform_gateway(
        enabled=True,
        gateway_type="bifrost",
        base_url="http://localhost:8080/litellm",
        master_key="bifrost-key",
        passthrough=False,
    )
    org_id, db = _org_db({"enabled": True})
    result = apply_llm_gateway(
        {"model": "gemini/gemini-2.5-flash", "api_key": "google-key", "messages": []},
        organization_id=org_id,
        db=db,
    )

    assert result["api_base"] == "http://localhost:8080/litellm"
    assert result["custom_llm_provider"] == "openai"
    assert result["model"] == "gemini/gemini-2.5-flash"


def test_apply_litellm_proxy_forces_openai_compatible_routing_for_gemini():
    _set_platform_gateway(
        enabled=True,
        gateway_type="litellm_proxy",
        base_url="http://localhost:4000",
        master_key="proxy-master",
        passthrough=False,
    )
    org_id, db = _org_db({"enabled": True})
    result = apply_llm_gateway(
        {"model": "gemini/gemini-2.5-flash", "api_key": "google-key", "messages": []},
        organization_id=org_id,
        db=db,
    )

    assert result["custom_llm_provider"] == "openai"
    assert result["model"] == "gemini/gemini-2.5-flash"


def test_apply_gateway_leaves_openai_models_unmodified():
    _set_platform_gateway(
        enabled=True,
        gateway_type="bifrost",
        base_url="http://localhost:8080/litellm",
        master_key="bifrost-key",
        passthrough=False,
    )
    org_id, db = _org_db({"enabled": True})
    result = apply_llm_gateway(
        {"model": "openai/gpt-4o-mini", "api_key": "sk-test", "messages": []},
        organization_id=org_id,
        db=db,
    )

    assert "custom_llm_provider" not in result
    assert result["model"] == "openai/gpt-4o-mini"
