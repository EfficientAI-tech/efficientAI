"""API tests for gateway-managed AI provider credentials."""

import pytest

from app.config import settings
from app.models.database import AIProvider
from app.services.ai.llm_gateway import is_gateway_managed_stored_key


def _set_platform_gateway_passthrough(passthrough: bool):
    settings.LLM_GATEWAY_PASSTHROUGH_PROVIDER_KEYS = passthrough


@pytest.fixture(autouse=True)
def _reset_gateway_settings():
    original = (
        settings.LLM_GATEWAY_ENABLED,
        settings.LLM_GATEWAY_PASSTHROUGH_PROVIDER_KEYS,
    )
    yield
    (
        settings.LLM_GATEWAY_ENABLED,
        settings.LLM_GATEWAY_PASSTHROUGH_PROVIDER_KEYS,
    ) = original


def test_create_aiprovider_without_key_when_gateway_managed(
    authenticated_client, db_session, org_id
):
    _set_platform_gateway_passthrough(False)

    response = authenticated_client.post(
        "/api/v1/aiproviders",
        json={"provider": "openai", "name": "OpenAI via gateway"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["provider"] == "openai"
    assert data["gateway_managed"] is True

    row = (
        db_session.query(AIProvider)
        .filter(AIProvider.organization_id == org_id)
        .first()
    )
    assert row is not None
    assert is_gateway_managed_stored_key(row.api_key) is True


def test_create_aiprovider_without_key_rejected_when_passthrough_enabled(
    authenticated_client,
):
    _set_platform_gateway_passthrough(True)

    response = authenticated_client.post(
        "/api/v1/aiproviders",
        json={"provider": "openai"},
    )
    assert response.status_code == 400


def test_llm_gateway_settings_expose_gateway_managed_flag(authenticated_client):
    _set_platform_gateway_passthrough(False)

    response = authenticated_client.get("/api/v1/organizations/llm-gateway")
    assert response.status_code == 200
    assert response.json()["gateway_managed_credentials"] is True
