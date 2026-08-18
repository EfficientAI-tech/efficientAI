"""API tests for integrations routes."""

import importlib
import json
from pathlib import Path

from app.api.v1.routes import integrations as integrations_route

prompt_sync_module = importlib.import_module("app.services.voice_providers.prompt_sync")
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "elevenlabs"


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


def test_list_integration_external_agents_elevenlabs(authenticated_client, monkeypatch, make_integration):
    integration = make_integration(platform="elevenlabs", api_key="encrypted")
    fixture = json.loads((FIXTURE_DIR / "agents_list.json").read_text())

    class _Provider:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def list_agents(self, **_kwargs):
            return {
                "agents": [
                    {
                        "id": fixture["agents"][0]["agent_id"],
                        "name": fixture["agents"][0]["name"],
                        "archived": fixture["agents"][0]["archived"],
                        "created_at": fixture["agents"][0]["created_at_unix_secs"],
                        "metadata": fixture["agents"][0],
                    }
                ],
                "has_more": fixture["has_more"],
                "next_cursor": fixture["next_cursor"],
            }

    monkeypatch.setattr(integrations_route, "decrypt_api_key", lambda _v: "decrypted")
    monkeypatch.setattr(integrations_route, "get_voice_provider", lambda _p: _Provider)

    response = authenticated_client.get(f"/api/v1/integrations/{integration.id}/external-agents")
    assert response.status_code == 200
    payload = response.json()
    assert payload["agents"][0]["id"].startswith("agent_")
    assert payload["agents"][0]["name"] == "Customer Support Agent"


def test_list_integration_external_agents_non_elevenlabs_rejected(
    authenticated_client, make_integration
):
    integration = make_integration(platform="murf", api_key="encrypted")
    response = authenticated_client.get(f"/api/v1/integrations/{integration.id}/external-agents")
    assert response.status_code == 400


def test_list_integration_external_agents_vapi(authenticated_client, monkeypatch, make_integration):
    integration = make_integration(platform="vapi", api_key="encrypted")

    class _Provider:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def list_agents(self, **_kwargs):
            return {
                "agents": [
                    {
                        "id": "assist_123",
                        "name": "Support Assistant",
                        "archived": False,
                        "created_at": "2026-01-01T00:00:00.000Z",
                        "metadata": {"id": "assist_123", "name": "Support Assistant"},
                    }
                ],
                "has_more": False,
                "next_cursor": None,
            }

    monkeypatch.setattr(integrations_route, "decrypt_api_key", lambda _v: "decrypted")
    monkeypatch.setattr(integrations_route, "get_voice_provider", lambda _p: _Provider)

    response = authenticated_client.get(f"/api/v1/integrations/{integration.id}/external-agents")
    assert response.status_code == 200
    payload = response.json()
    assert payload["agents"][0]["id"] == "assist_123"
    assert payload["agents"][0]["name"] == "Support Assistant"


def test_list_integration_external_agents_retell(authenticated_client, monkeypatch, make_integration):
    integration = make_integration(platform="retell", api_key="encrypted")

    class _Provider:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def list_agents(self, **_kwargs):
            return {
                "agents": [
                    {
                        "id": "agent_retell_1",
                        "name": "Retell Agent",
                        "archived": False,
                        "created_at": "2026-01-02T00:00:00.000Z",
                        "metadata": {"agent_id": "agent_retell_1", "agent_name": "Retell Agent"},
                    }
                ],
                "has_more": False,
                "next_cursor": None,
            }

    monkeypatch.setattr(integrations_route, "decrypt_api_key", lambda _v: "decrypted")
    monkeypatch.setattr(integrations_route, "get_voice_provider", lambda _p: _Provider)

    response = authenticated_client.get(f"/api/v1/integrations/{integration.id}/external-agents")
    assert response.status_code == 200
    payload = response.json()
    assert payload["agents"][0]["id"] == "agent_retell_1"
