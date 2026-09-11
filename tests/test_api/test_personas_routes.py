"""API tests for persona routes."""


def test_create_and_list_personas(authenticated_client):
    payload = {
        "name": "Persona One",
        "gender": "neutral",
        "tts_provider": "openai",
        "tts_voice_id": "alloy",
        "tts_voice_name": "Alloy",
        "is_custom": False,
    }
    create_response = authenticated_client.post("/api/v1/personas", json=payload)

    assert create_response.status_code == 201
    body = create_response.json()
    assert body["name"] == "Persona One"
    assert body["tts_provider"] == "openai"

    list_response = authenticated_client.get("/api/v1/personas")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1


def test_get_and_update_persona(authenticated_client):
    create_response = authenticated_client.post(
        "/api/v1/personas",
        json={
            "name": "Persona Update",
            "gender": "female",
            "is_custom": True,
        },
    )
    persona_id = create_response.json()["id"]

    get_response = authenticated_client.get(f"/api/v1/personas/{persona_id}")
    assert get_response.status_code == 200
    assert get_response.json()["name"] == "Persona Update"

    update_response = authenticated_client.put(
        f"/api/v1/personas/{persona_id}",
        json={"name": "Persona Updated", "tts_provider": "elevenlabs"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "Persona Updated"
    assert update_response.json()["tts_provider"] == "elevenlabs"


def test_update_persona_rejects_tts_provider_change(authenticated_client):
    create_response = authenticated_client.post(
        "/api/v1/personas",
        json={
            "name": "Locked Provider",
            "gender": "female",
            "tts_provider": "openai",
            "tts_voice_id": "alloy",
            "tts_voice_name": "Alloy",
        },
    )
    assert create_response.status_code == 201
    persona_id = create_response.json()["id"]

    update_response = authenticated_client.put(
        f"/api/v1/personas/{persona_id}",
        json={"tts_provider": "elevenlabs"},
    )
    assert update_response.status_code == 422
    assert "tts_provider" in update_response.json()["detail"].lower()

    voice_update = authenticated_client.put(
        f"/api/v1/personas/{persona_id}",
        json={"tts_voice_id": "echo", "tts_voice_name": "Echo"},
    )
    assert voice_update.status_code == 200
    assert voice_update.json()["tts_provider"] == "openai"
    assert voice_update.json()["tts_voice_id"] == "echo"


def test_get_agent_prompt_sources(authenticated_client, make_agent, db_session):
    agent = make_agent(
        name="Support Bot",
        description="Test agent prompt body",
    )
    agent.provider_prompt = "Production prompt body"
    db_session.commit()
    db_session.refresh(agent)

    response = authenticated_client.get(f"/api/v1/personas/agent-prompt-sources/{agent.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["agent_name"] == "Support Bot"
    assert "Test agent prompt body" in body["test_agent_prompt"]
    assert body["agent_prompt"] == "Production prompt body"


def test_clone_persona(authenticated_client):
    create_response = authenticated_client.post(
        "/api/v1/personas",
        json={"name": "Persona Clone Source", "gender": "male", "is_custom": False},
    )
    source_id = create_response.json()["id"]

    clone_response = authenticated_client.post(
        f"/api/v1/personas/{source_id}/clone",
        json={"name": "Persona Clone Copy"},
    )

    assert clone_response.status_code == 201
    assert clone_response.json()["name"] == "Persona Clone Copy"


def test_create_persona_with_prompt_and_tts_config(authenticated_client):
    payload = {
        "name": "Detailed Persona",
        "gender": "female",
        "tts_provider": "elevenlabs",
        "tts_voice_id": "21m00Tcm4TlvDq8ikWAM",
        "tts_voice_name": "Rachel",
        "description": "An impatient customer calling about a late delivery.",
        "tts_config": {"speed": 1.1, "stability": 0.4},
        "llm_temperature": 0.9,
        "max_turns": 12,
        "response_delay_ms": 800,
        "allow_interruptions": True,
    }
    response = authenticated_client.post("/api/v1/personas", json=payload)
    assert response.status_code == 201
    body = response.json()
    assert body["description"] == payload["description"]
    assert body["tts_config"]["speed"] == 1.1
    assert body["llm_temperature"] == 0.9
    assert body["max_turns"] == 12
    assert body["allow_interruptions"] is True


def test_create_persona_rejects_invalid_tts_config(authenticated_client):
    response = authenticated_client.post(
        "/api/v1/personas",
        json={
            "name": "Bad Config",
            "gender": "neutral",
            "tts_provider": "openai",
            "tts_config": {"stability": 0.5},
        },
    )
    assert response.status_code == 422
