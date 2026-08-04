"""Tests for multi-gateway LLM resolver (Bifrost + LiteLLM Proxy)."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.config import settings
from app.services.ai import llm_gateway as gateway_module
from app.services.ai.llm_gateway import (
    apply_llm_gateway,
    CredentialRoutingContext,
    LITELLM_GATEWAY_PLACEHOLDER_API_KEY,
    normalize_bifrost_native_url,
    resolve_effective_routing,
    resolve_litellm_model,
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
        settings.LLM_GATEWAY_INTERFACE,
    )
    yield
    (
        settings.LLM_GATEWAY_ENABLED,
        settings.LLM_GATEWAY_TYPE,
        settings.LLM_GATEWAY_BASE_URL,
        settings.LLM_GATEWAY_VIRTUAL_KEY,
        settings.LLM_GATEWAY_MASTER_KEY,
        settings.LLM_GATEWAY_PASSTHROUGH_PROVIDER_KEYS,
        settings.LLM_GATEWAY_INTERFACE,
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


def test_apply_bifrost_gateway_forces_openai_routing_for_bare_gemini_model_name():
    _set_platform_gateway(
        enabled=True,
        gateway_type="bifrost",
        base_url="http://localhost:8080",
        passthrough=False,
    )
    settings.LLM_GATEWAY_INTERFACE = "native_openai"
    org_id, db = _org_db({"enabled": True})
    result = apply_llm_gateway(
        {"model": "gemini-2.5-flash", "messages": []},
        organization_id=org_id,
        db=db,
    )

    assert result["api_base"] == "http://localhost:8080/v1"
    assert result["custom_llm_provider"] == "openai"
    assert result["model"] == "gemini-2.5-flash"


def test_apply_litellm_proxy_forces_openai_compatible_routing_for_gemini():
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


def test_apply_bifrost_gateway_forces_openai_compatible_routing_for_azure():
    _set_platform_gateway(
        enabled=True,
        gateway_type="bifrost",
        base_url="http://localhost:8080/litellm",
        passthrough=False,
    )
    org_id, db = _org_db({"enabled": True})
    result = apply_llm_gateway(
        {"model": "azure/azure-openai-gpt4", "messages": []},
        organization_id=org_id,
        db=db,
    )

    assert result["custom_llm_provider"] == "openai"
    assert result["model"] == "openai/gpt-4o-mini"


def test_apply_gateway_without_model_still_forces_openai_routing():
    """Gateway calls always use OpenAI-compatible routing, even without model."""
    _set_platform_gateway(
        enabled=True,
        gateway_type="bifrost",
        base_url="http://localhost:8080/litellm",
        passthrough=False,
    )
    org_id, db = _org_db({"enabled": True})
    result = apply_llm_gateway(
        {"api_key": "google-key"},
        organization_id=org_id,
        db=db,
    )

    assert result["custom_llm_provider"] == "openai"


def test_apply_gateway_routing_model_enables_gemini_proxy_routing_for_gepa_batch():
    _set_platform_gateway(
        enabled=True,
        gateway_type="bifrost",
        base_url="http://localhost:8080/litellm",
        passthrough=False,
    )
    org_id, db = _org_db({"enabled": True})
    result = apply_llm_gateway(
        {"api_key": "google-key"},
        organization_id=org_id,
        db=db,
        model="gemini/gemini-2.5-flash",
    )

    assert result["custom_llm_provider"] == "openai"
    assert "model" not in result


def test_credential_direct_overrides_org_gateway():
    _set_platform_gateway(
        enabled=True,
        base_url="http://bifrost.example.com/litellm",
    )
    org_id, db = _org_db({"enabled": True})
    ctx = CredentialRoutingContext(routing_mode="direct")
    config, effective = resolve_effective_routing(org_id, db, ctx)
    assert config is None
    assert effective == "direct"
    assert resolve_llm_gateway(org_id, db, credential=ctx) is None


def test_credential_gateway_overrides_org_opt_out():
    _set_platform_gateway(
        enabled=True,
        base_url="http://bifrost.example.com/litellm",
        virtual_key="platform-vk",
    )
    org_id, db = _org_db({"enabled": False})
    ctx = CredentialRoutingContext(routing_mode="gateway")
    config, effective = resolve_effective_routing(org_id, db, ctx)
    assert config is not None
    assert effective == "bifrost"
    assert config.api_base == "http://bifrost.example.com/litellm"


def test_credential_gateway_raises_when_no_base_url():
    _set_platform_gateway(enabled=False)
    org_id, db = _org_db({"enabled": False})
    ctx = CredentialRoutingContext(routing_mode="gateway")
    with pytest.raises(RuntimeError, match="no base_url"):
        resolve_effective_routing(org_id, db, ctx)


def test_resolve_litellm_model_uses_gateway_model_when_active():
    ctx = CredentialRoutingContext(routing_mode="gateway", gateway_model="production-gpt4")
    assert resolve_litellm_model(
        workload_model_str="openai/gpt-4o",
        gateway_active=True,
        credential=ctx,
    ) == "production-gpt4"


def test_resolve_litellm_model_keeps_workload_model_when_direct():
    ctx = CredentialRoutingContext(routing_mode="direct", gateway_model="production-gpt4")
    assert resolve_litellm_model(
        workload_model_str="openai/gpt-4o",
        gateway_active=False,
        credential=ctx,
    ) == "openai/gpt-4o"


def test_normalize_bifrost_native_url_strips_chat_completions_path():
    assert (
        normalize_bifrost_native_url("http://localhost:8080/v1/chat/completions")
        == "http://localhost:8080/v1"
    )


def test_normalize_bifrost_native_url_strips_litellm_and_chat_paths():
    assert (
        normalize_bifrost_native_url("http://localhost:8080/litellm/v1/chat/completions")
        == "http://localhost:8080/v1"
    )


def test_normalize_bifrost_native_url_appends_v1_to_host_root():
    assert normalize_bifrost_native_url("http://localhost:8080") == "http://localhost:8080/v1"


def test_apply_gateway_skips_injection_for_direct_credential():
    _set_platform_gateway(
        enabled=True,
        base_url="http://localhost:8080/litellm",
        virtual_key="vk-123",
    )
    org_id, db = _org_db({"enabled": True})
    ctx = CredentialRoutingContext(routing_mode="direct")
    result = apply_llm_gateway(
        {"model": "openai/gpt-4o-mini", "api_key": "sk-test", "messages": []},
        organization_id=org_id,
        db=db,
        credential=ctx,
    )
    assert "api_base" not in result
    assert result["api_key"] == "sk-test"


def test_native_openai_interface_strips_litellm_suffix():
    _set_platform_gateway(
        enabled=True,
        base_url="http://bifrost.example.com:8080",
    )
    settings.LLM_GATEWAY_INTERFACE = "native_openai"
    org_id, db = _org_db({"enabled": True})
    config = resolve_llm_gateway(org_id, db)
    assert config is not None
    assert config.gateway_interface == "native_openai"
    assert config.api_base == "http://bifrost.example.com:8080/v1"


def test_native_openai_does_not_append_litellm():
    _set_platform_gateway(
        enabled=True,
        base_url="http://bifrost.example.com:8080",
    )
    settings.LLM_GATEWAY_INTERFACE = "native_openai"
    org_id, db = _org_db({"enabled": True})
    result = apply_llm_gateway(
        {"model": "custom-gemma", "api_key": "sk-test", "messages": []},
        organization_id=org_id,
        db=db,
    )
    assert result["api_base"] == "http://bifrost.example.com:8080/v1"


def test_credential_gateway_base_url_overrides_org():
    _set_platform_gateway(
        enabled=True,
        base_url="http://platform-bifrost:8080/litellm",
        virtual_key="platform-vk",
    )
    org_id, db = _org_db(
        {
            "enabled": True,
            "base_url": "http://org-bifrost:9090/litellm",
        }
    )
    ctx = CredentialRoutingContext(
        routing_mode="gateway",
        gateway_base_url="http://credential-bifrost:7070/litellm",
    )
    config, _ = resolve_effective_routing(org_id, db, ctx)
    assert config is not None
    assert config.api_base == "http://credential-bifrost:7070/litellm"


def test_credential_native_interface_overrides_org_shim():
    _set_platform_gateway(
        enabled=True,
        base_url="http://bifrost.example.com:8080/litellm",
    )
    org_id, db = _org_db({"enabled": True, "gateway_interface": "litellm_shim"})
    ctx = CredentialRoutingContext(
        routing_mode="gateway",
        gateway_interface="native_openai",
        gateway_base_url="http://bifrost.example.com:8080",
    )
    config, _ = resolve_effective_routing(org_id, db, ctx)
    assert config is not None
    assert config.gateway_interface == "native_openai"
    assert config.api_base == "http://bifrost.example.com:8080/v1"


def test_credential_auth_secret_env_overrides_org_virtual_key(monkeypatch):
    _set_platform_gateway(
        enabled=True,
        base_url="http://bifrost.example.com:8080",
        virtual_key="platform-vk",
    )
    settings.LLM_GATEWAY_INTERFACE = "native_openai"
    monkeypatch.setenv("BIFROST_PRD_VK_GEMMA", "env-vk-secret")
    org_id, db = _org_db({"enabled": True, "virtual_key": "encrypted-org-vk"})
    monkeypatch.setattr(
        gateway_module,
        "_decrypt_org_virtual_key",
        lambda _raw: "org-vk",
    )
    ctx = CredentialRoutingContext(
        routing_mode="gateway",
        gateway_interface="native_openai",
        gateway_base_url="http://llm-gateway.prd.example.int",
        gateway_auth_header="x-bf-vk",
        gateway_auth_secret_env="BIFROST_PRD_VK_GEMMA",
    )
    result = apply_llm_gateway(
        {"model": "inhouse-llm-server-v2//models/gemma", "api_key": "sk-test", "messages": []},
        organization_id=org_id,
        db=db,
        credential=ctx,
    )
    assert result["api_base"] == "http://llm-gateway.prd.example.int/v1"
    assert result["extra_headers"]["x-bf-vk"] == "env-vk-secret"


def test_credential_authorization_header_uses_bearer_prefix():
    _set_platform_gateway(
        enabled=True,
        base_url="http://bifrost.example.com:8080",
    )
    settings.LLM_GATEWAY_INTERFACE = "native_openai"
    org_id, db = _org_db({"enabled": True})
    ctx = CredentialRoutingContext(
        routing_mode="gateway",
        gateway_auth_header="Authorization",
        gateway_auth_secret="sk-bf-test-key",
    )
    result = apply_llm_gateway(
        {"model": "custom-model", "messages": []},
        organization_id=org_id,
        db=db,
        credential=ctx,
    )
    assert result["extra_headers"]["Authorization"] == "Bearer sk-bf-test-key"


def test_credential_gateway_extra_headers_are_merged():
    _set_platform_gateway(
        enabled=True,
        base_url="http://bifrost.example.com:8080",
        virtual_key="platform-vk",
    )
    settings.LLM_GATEWAY_INTERFACE = "native_openai"
    org_id, db = _org_db({"enabled": True})
    ctx = CredentialRoutingContext(
        routing_mode="gateway",
        gateway_auth_header="x-bf-vk",
        gateway_auth_secret_env=None,
        gateway_auth_secret="credential-vk",
        gateway_extra_headers={
            "X-Custom-Tenant": "prod",
            "X-Request-Source": "efficientai",
        },
    )
    result = apply_llm_gateway(
        {"model": "custom-model", "messages": []},
        organization_id=org_id,
        db=db,
        credential=ctx,
    )
    assert result["extra_headers"]["X-Custom-Tenant"] == "prod"
    assert result["extra_headers"]["X-Request-Source"] == "efficientai"
    assert result["extra_headers"]["x-bf-vk"] == "credential-vk"


def test_gateway_auth_header_overrides_duplicate_extra_header():
    _set_platform_gateway(enabled=True, base_url="http://bifrost.example.com:8080")
    org_id, db = _org_db({"enabled": True})
    ctx = CredentialRoutingContext(
        routing_mode="gateway",
        gateway_auth_header="x-bf-vk",
        gateway_auth_secret="resolved-vk",
        gateway_extra_headers={"x-bf-vk": "stale-vk"},
    )
    result = apply_llm_gateway(
        {"model": "custom-model", "messages": []},
        organization_id=org_id,
        db=db,
        credential=ctx,
    )
    assert result["extra_headers"]["x-bf-vk"] == "resolved-vk"
