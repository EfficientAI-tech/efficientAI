"""API tests for integrations routes."""

import importlib

from app.api.v1.routes import integrations as integrations_route

prompt_sync_module = importlib.import_module("app.services.voice_providers.prompt_sync")


def test_create_and_list_integrations(authenticated_client):
    payload = {"platform": "retell", "api_key": "secret-key", "name": "Retell Main"}
    create_response = authenticated_client.post("/api/v1/integrations", json=payload)

    assert create_response.status_code == 201
    body = create_response.json()
    assert body["platform"] == "retell"
    assert body["name"] == "Retell Main"

    list_response = authenticated_client.get("/api/v1/integrations")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1


def test_update_integration(authenticated_client, make_integration):
    integration = make_integration(platform="retell")
    response = authenticated_client.put(
        f"/api/v1/integrations/{integration.id}",
        json={"name": "Updated Integration", "public_key": "pub-key"},
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Updated Integration"
    assert response.json()["public_key"] == "pub-key"


def test_get_integration_api_key(authenticated_client, monkeypatch, make_integration):
    integration = make_integration(platform="retell", api_key="encrypted")
    monkeypatch.setattr(integrations_route, "decrypt_api_key", lambda _v: "decrypted-key")

    response = authenticated_client.get(f"/api/v1/integrations/{integration.id}/api-key")

    assert response.status_code == 200
    assert response.json()["api_key"] == "decrypted-key"


def test_create_smallest_integration_validates_key_and_sets_default_name(authenticated_client, monkeypatch):
    calls = {"count": 0}

    def _validate(api_key: str):
        calls["count"] += 1
        assert api_key == "smallest-secret"
        return {"email": "owner@smallest.ai"}

    monkeypatch.setattr(integrations_route, "_validate_smallest_connection", _validate)

    response = authenticated_client.post(
        "/api/v1/integrations",
        json={"platform": "smallest", "api_key": "smallest-secret"},
    )

    assert response.status_code == 201
    assert response.json()["platform"] == "smallest"
    assert response.json()["name"] == "Smallest (owner@smallest.ai)"
    assert calls["count"] == 1


def test_update_smallest_integration_validates_updated_key(authenticated_client, monkeypatch, make_integration):
    integration = make_integration(platform="smallest", api_key="encrypted")
    calls = {"count": 0}

    def _validate(api_key: str):
        calls["count"] += 1
        assert api_key == "next-smallest-key"
        return {"email": "owner@smallest.ai"}

    monkeypatch.setattr(integrations_route, "_validate_smallest_connection", _validate)

    response = authenticated_client.put(
        f"/api/v1/integrations/{integration.id}",
        json={"api_key": "next-smallest-key"},
    )

    assert response.status_code == 200
    assert calls["count"] == 1


def test_preview_integration_agent_prompt_success(authenticated_client, monkeypatch, make_integration):
    integration = make_integration(platform="retell")
    monkeypatch.setattr(
        prompt_sync_module,
        "fetch_provider_prompt",
        lambda _integration, agent_id: f"Prompt for {agent_id}",
    )

    response = authenticated_client.post(
        f"/api/v1/integrations/{integration.id}/preview-agent-prompt",
        json={"voice_ai_agent_id": "external-agent-123"},
    )

    assert response.status_code == 200
    assert response.json()["provider_prompt"] == "Prompt for external-agent-123"


def test_preview_integration_agent_prompt_not_found(authenticated_client):
    response = authenticated_client.post(
        "/api/v1/integrations/11111111-1111-1111-1111-111111111111/preview-agent-prompt",
        json={"voice_ai_agent_id": "external-agent-123"},
    )

    assert response.status_code == 404


def test_preview_integration_agent_prompt_empty(authenticated_client, monkeypatch, make_integration):
    integration = make_integration(platform="vapi")
    monkeypatch.setattr(
        prompt_sync_module,
        "fetch_provider_prompt",
        lambda _integration, _agent_id: None,
    )

    response = authenticated_client.post(
        f"/api/v1/integrations/{integration.id}/preview-agent-prompt",
        json={"voice_ai_agent_id": "external-agent-123"},
    )

    assert response.status_code == 422


def test_list_integration_voice_agents_success(authenticated_client, monkeypatch, make_integration):
    integration = make_integration(platform="elevenlabs")
    catalog_module = importlib.import_module("app.services.voice_providers.voice_agent_catalog")

    class _Result:
        agents = [{"id": "agent-1", "name": "Support Bot"}]
        platform = "elevenlabs"
        cached = False
        truncated = False
        list_supported = True
        message = None

    monkeypatch.setattr(
        catalog_module,
        "list_integration_voice_agents",
        lambda _integration, refresh=False, search=None: _Result(),
    )

    response = authenticated_client.get(f"/api/v1/integrations/{integration.id}/voice-agents")

    assert response.status_code == 200
    body = response.json()
    assert body["platform"] == "elevenlabs"
    assert body["agents"] == [{"id": "agent-1", "name": "Support Bot"}]
    assert body["list_supported"] is True


def test_list_integration_voice_agents_not_found(authenticated_client):
    response = authenticated_client.get(
        "/api/v1/integrations/11111111-1111-1111-1111-111111111111/voice-agents",
    )

    assert response.status_code == 404


def test_list_integration_voice_agents_provider_error(authenticated_client, monkeypatch, make_integration):
    integration = make_integration(platform="vapi")
    catalog_module = importlib.import_module("app.services.voice_providers.voice_agent_catalog")

    def _raise(_integration, refresh=False, search=None):
        raise ValueError("Provider unavailable")

    monkeypatch.setattr(catalog_module, "list_integration_voice_agents", _raise)

    response = authenticated_client.get(f"/api/v1/integrations/{integration.id}/voice-agents")

    assert response.status_code == 502
    assert "Provider unavailable" in response.json()["detail"]
