"""API tests for organization LLM gateway settings."""

import pytest

from app.config import settings
from app.models.database import Organization


def _set_platform_gateway(**kwargs):
    settings.LLM_GATEWAY_ENABLED = kwargs.get("enabled", False)
    settings.LLM_GATEWAY_TYPE = kwargs.get("gateway_type", "bifrost")
    settings.LLM_GATEWAY_BASE_URL = kwargs.get("base_url")
    settings.LLM_GATEWAY_VIRTUAL_KEY = kwargs.get("virtual_key")
    settings.LLM_GATEWAY_MASTER_KEY = kwargs.get("master_key")
    settings.LLM_GATEWAY_PASSTHROUGH_PROVIDER_KEYS = kwargs.get("passthrough", True)


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


def test_get_llm_gateway_settings_defaults(authenticated_client):
    _set_platform_gateway(
        enabled=True,
        base_url="http://platform-bifrost/litellm",
    )

    response = authenticated_client.get("/api/v1/organizations/llm-gateway")
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "inherit"
    assert data["gateway_type"] == "inherit"
    assert data["platform_enabled"] is True
    assert data["platform_gateway_type"] == "bifrost"
    assert data["platform_base_url"] == "http://platform-bifrost/litellm"
    assert data["effective_routing"] == "bifrost"


def test_update_llm_gateway_settings_persists_bifrost_override(
    authenticated_client, db_session, org_id
):
    _set_platform_gateway(enabled=False)

    response = authenticated_client.put(
        "/api/v1/organizations/llm-gateway",
        json={
            "mode": "enabled",
            "gateway_type": "bifrost",
            "base_url": "http://org-bifrost:8080/litellm",
            "virtual_key": "org-virtual-key",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "enabled"
    assert data["gateway_type"] == "bifrost"
    assert data["base_url"] == "http://org-bifrost:8080/litellm"
    assert data["has_virtual_key"] is True
    assert data["effective_routing"] == "bifrost"
    assert data["effective_base_url"] == "http://org-bifrost:8080/litellm"

    org = db_session.query(Organization).filter(Organization.id == org_id).first()
    assert org.llm_gateway_settings["enabled"] is True
    assert org.llm_gateway_settings["gateway_type"] == "bifrost"
    assert org.llm_gateway_settings["virtual_key"]


def test_update_llm_gateway_settings_persists_litellm_proxy_override(
    authenticated_client, db_session, org_id
):
    _set_platform_gateway(enabled=False)

    response = authenticated_client.put(
        "/api/v1/organizations/llm-gateway",
        json={
            "mode": "enabled",
            "gateway_type": "litellm_proxy",
            "base_url": "http://org-proxy:4000",
            "master_key": "org-master-key",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["gateway_type"] == "litellm_proxy"
    assert data["has_master_key"] is True
    assert data["effective_routing"] == "litellm_proxy"
    assert data["effective_base_url"] == "http://org-proxy:4000"

    org = db_session.query(Organization).filter(Organization.id == org_id).first()
    assert org.llm_gateway_settings["gateway_type"] == "litellm_proxy"
    assert org.llm_gateway_settings["master_key"]


def test_update_llm_gateway_settings_rejects_invalid_url(authenticated_client):
    response = authenticated_client.put(
        "/api/v1/organizations/llm-gateway",
        json={
            "mode": "enabled",
            "gateway_type": "bifrost",
            "base_url": "not-a-valid-url",
        },
    )
    assert response.status_code == 400
