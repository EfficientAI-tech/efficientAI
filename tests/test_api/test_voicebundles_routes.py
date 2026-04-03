"""API tests for voicebundles routes."""

from uuid import uuid4


def _voicebundle_payload(**overrides):
    payload = {
        "name": "Support Voice Bundle",
        "description": "Bundle for support calls",
        "bundle_type": "stt_llm_tts",
        "stt_provider": "openai",
        "stt_model": "whisper-1",
        "llm_provider": "openai",
        "llm_model": "gpt-4o-mini",
        "tts_provider": "openai",
        "tts_model": "gpt-4o-mini-tts",
    }
    payload.update(overrides)
    return payload


def test_create_list_get_update_voicebundle(authenticated_client):
    create_response = authenticated_client.post(
        "/api/v1/voicebundles",
        json=_voicebundle_payload(),
    )
    assert create_response.status_code == 201
    created = create_response.json()
    voicebundle_id = created["id"]
    assert created["name"] == "Support Voice Bundle"

    list_response = authenticated_client.get("/api/v1/voicebundles")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    get_response = authenticated_client.get(f"/api/v1/voicebundles/{voicebundle_id}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == voicebundle_id

    update_response = authenticated_client.put(
        f"/api/v1/voicebundles/{voicebundle_id}",
        json={"name": "Updated Bundle", "description": "new description"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "Updated Bundle"


def test_delete_voicebundle_with_dependencies_requires_force(
    authenticated_client, make_voice_bundle, make_agent
):
    voicebundle = make_voice_bundle()
    make_agent(voice_bundle_id=voicebundle.id)

    response = authenticated_client.delete(f"/api/v1/voicebundles/{voicebundle.id}")

    assert response.status_code == 409
    assert "dependencies" in response.json()["detail"]
    assert response.json()["detail"]["dependencies"]["agents"] == 1


def test_delete_voicebundle_force_unlinks_dependencies(
    authenticated_client, make_voice_bundle, make_agent
):
    voicebundle = make_voice_bundle()
    agent = make_agent(voice_bundle_id=voicebundle.id)

    response = authenticated_client.delete(f"/api/v1/voicebundles/{voicebundle.id}?force=true")

    assert response.status_code == 200
    assert response.json()["unlinked"]["agents"] == 1

    list_response = authenticated_client.get("/api/v1/voicebundles")
    assert list_response.status_code == 200
    assert list_response.json() == []

    refreshed_agent = authenticated_client.get(f"/api/v1/agents/{agent.id}")
    assert refreshed_agent.status_code == 200
    assert refreshed_agent.json()["voice_bundle_id"] is None
