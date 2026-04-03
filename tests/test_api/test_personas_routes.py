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
