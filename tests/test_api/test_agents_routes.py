"""API tests for agent routes."""


def test_create_agent_success(authenticated_client, make_integration):
    integration = make_integration()
    payload = {
        "name": "Support Agent",
        "phone_number": "+1234567890",
        "language": "en",
        "description": "This test support agent handles customer issues and guides users clearly.",
        "call_type": "outbound",
        "call_medium": "phone_call",
        "voice_ai_integration_id": str(integration.id),
        "voice_ai_agent_id": "provider-agent-123",
    }

    response = authenticated_client.post("/api/v1/agents", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Support Agent"
    assert body["voice_ai_integration_id"] == str(integration.id)


def test_create_agent_with_missing_integration_returns_404(authenticated_client):
    payload = {
        "name": "Support Agent",
        "phone_number": "+1234567890",
        "language": "en",
        "description": "This test support agent handles customer issues and guides users clearly.",
        "call_type": "outbound",
        "call_medium": "phone_call",
        "voice_ai_integration_id": "11111111-1111-1111-1111-111111111111",
        "voice_ai_agent_id": "provider-agent-123",
    }

    response = authenticated_client.post("/api/v1/agents", json=payload)

    assert response.status_code == 404
    assert response.json()["detail"] == "Integration not found or inactive"


def test_list_and_get_agent(authenticated_client, make_agent):
    agent = make_agent(name="Agent Listed", agent_id="777777")

    list_response = authenticated_client.get("/api/v1/agents")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    get_response = authenticated_client.get(f"/api/v1/agents/{agent.agent_id}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == str(agent.id)


def test_agent_delete_impact_without_dependencies(authenticated_client, make_agent):
    agent = make_agent(name="Impact Agent", agent_id="888888")

    response = authenticated_client.get(f"/api/v1/agents/{agent.agent_id}/delete-impact")

    assert response.status_code == 200
    body = response.json()
    assert body["agent_name"] == "Impact Agent"
    assert body["dependencies"] == {}
    assert body["can_delete_without_force"] is True
