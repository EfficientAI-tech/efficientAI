"""API tests for agent routes."""


def test_create_agent_success(authenticated_client, make_integration, make_voice_bundle):
    integration = make_integration()
    voice_bundle = make_voice_bundle()
    payload = {
        "name": "Support Agent",
        "phone_number": "+1234567890",
        "language": "en",
        "description": "This test support agent handles customer issues and guides users clearly.",
        "call_type": "outbound",
        "call_medium": "phone_call",
        "voice_bundle_id": str(voice_bundle.id),
        "voice_ai_integration_id": str(integration.id),
        "voice_ai_agent_id": "provider-agent-123",
    }

    response = authenticated_client.post("/api/v1/agents", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Support Agent"
    assert body["voice_ai_integration_id"] == str(integration.id)


def test_create_agent_with_provider_prompt(authenticated_client, make_voice_bundle):
    voice_bundle = make_voice_bundle()
    production_prompt = (
        "You are a helpful customer support agent that handles billing questions "
        "and order status requests professionally."
    )
    payload = {
        "name": "Telephony Agent",
        "phone_number": "+1234567890",
        "language": "en",
        "description": "This test support agent handles customer issues and guides users clearly.",
        "call_type": "outbound",
        "call_medium": "phone_call",
        "voice_bundle_id": str(voice_bundle.id),
        "provider_prompt": production_prompt,
    }

    response = authenticated_client.post("/api/v1/agents", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["provider_prompt"] == production_prompt
    assert body["voice_ai_integration_id"] is None


def test_create_agent_requires_voice_bundle(authenticated_client):
    payload = {
        "name": "Support Agent",
        "phone_number": "+1234567890",
        "language": "en",
        "description": "This test support agent handles customer issues and guides users clearly.",
        "call_type": "outbound",
        "call_medium": "phone_call",
    }

    response = authenticated_client.post("/api/v1/agents", json=payload)

    assert response.status_code == 422


def test_create_agent_with_missing_voice_bundle_returns_400(authenticated_client):
    payload = {
        "name": "Support Agent",
        "phone_number": "+1234567890",
        "language": "en",
        "description": "This test support agent handles customer issues and guides users clearly.",
        "call_type": "outbound",
        "call_medium": "phone_call",
        "voice_bundle_id": "11111111-1111-1111-1111-111111111111",
    }

    response = authenticated_client.post("/api/v1/agents", json=payload)

    assert response.status_code == 400
    assert response.json()["detail"] == "Active voice bundle not found"


def test_create_agent_with_missing_integration_returns_404(authenticated_client, make_voice_bundle):
    voice_bundle = make_voice_bundle()
    payload = {
        "name": "Support Agent",
        "phone_number": "+1234567890",
        "language": "en",
        "description": "This test support agent handles customer issues and guides users clearly.",
        "call_type": "outbound",
        "call_medium": "phone_call",
        "voice_bundle_id": str(voice_bundle.id),
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
    assert list_response.json()[0]["silence_hangup_secs"] == 15

    get_response = authenticated_client.get(f"/api/v1/agents/{agent.agent_id}")
    assert get_response.status_code == 200
    body = get_response.json()
    assert body["id"] == str(agent.id)
    assert body["silence_hangup_secs"] == 15


def test_update_agent_persists_silence_hangup_secs(authenticated_client, make_agent):
    agent = make_agent(name="Silence Agent", agent_id="666666")

    update_response = authenticated_client.put(
        f"/api/v1/agents/{agent.agent_id}",
        json={"silence_hangup_secs": 60},
    )
    assert update_response.status_code == 200
    assert update_response.json()["silence_hangup_secs"] == 60

    get_response = authenticated_client.get(f"/api/v1/agents/{agent.agent_id}")
    assert get_response.status_code == 200
    assert get_response.json()["silence_hangup_secs"] == 60


def test_agent_delete_impact_without_dependencies(authenticated_client, make_agent):
    agent = make_agent(name="Impact Agent", agent_id="888888")

    response = authenticated_client.get(f"/api/v1/agents/{agent.agent_id}/delete-impact")

    assert response.status_code == 200
    body = response.json()
    assert body["agent_name"] == "Impact Agent"
    assert body["dependencies"] == {}
    assert body["can_delete_without_force"] is True


def _agent_payload(**overrides):
    payload = {
        "name": "Another Agent",
        "language": "en",
        "description": "This test support agent handles customer issues and guides users clearly.",
        "call_type": "outbound",
        "call_medium": "phone_call",
    }
    payload.update(overrides)
    return payload


def test_create_agent_duplicate_phone_returns_409(authenticated_client, make_agent, make_voice_bundle):
    make_agent(name="Existing Agent", phone_number="+19998887777")
    voice_bundle = make_voice_bundle()

    response = authenticated_client.post(
        "/api/v1/agents",
        json=_agent_payload(phone_number="+19998887777", voice_bundle_id=str(voice_bundle.id)),
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["agent_name"] == "Existing Agent"
    assert "already assigned" in detail["message"]


def test_update_agent_duplicate_phone_returns_409(authenticated_client, make_agent):
    owner = make_agent(name="Owner Agent", phone_number="+18887776666", agent_id="111111")
    make_agent(name="Other Agent", phone_number="+17776665555", agent_id="222222")

    response = authenticated_client.put(
        f"/api/v1/agents/{owner.agent_id}",
        json={"phone_number": "+17776665555"},
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["agent_name"] == "Other Agent"


def test_check_phone_assignment_available(authenticated_client):
    response = authenticated_client.get(
        "/api/v1/agents/check-phone-assignment",
        params={"phone_number": "+16665554444"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["conflict"] is None


def test_check_phone_assignment_conflict(authenticated_client, make_agent):
    make_agent(name="Mapped Agent", phone_number="+15554443333")

    response = authenticated_client.get(
        "/api/v1/agents/check-phone-assignment",
        params={"phone_number": "+15554443333"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["conflict"]["agent_name"] == "Mapped Agent"


def test_check_phone_assignment_requires_input(authenticated_client):
    response = authenticated_client.get("/api/v1/agents/check-phone-assignment")

    assert response.status_code == 400
