"""API tests for voice-agent routes."""


def test_voice_agent_connect_returns_ws_url(authenticated_client, user_context, make_ai_provider):
    # Ensure org has a Google provider so /connect validation passes.
    make_ai_provider(provider="google")

    response = authenticated_client.get("/api/v1/voice-agent/connect?X-API-Key=test_api_key_123")

    assert response.status_code == 200
    assert "/api/v1/voice-agent/ws" in response.json()["ws_url"]
    assert "X-API-Key=test_api_key_123" in response.json()["ws_url"]


def test_voice_agent_audio_lists_files(authenticated_client, monkeypatch):
    from app.api.v1.routes import voice_agent as voice_agent_routes

    monkeypatch.setattr(
        voice_agent_routes.s3_service,
        "list_audio_files",
        lambda **_kwargs: [
            {
                "key": "org/audio/response.mp3",
                "filename": "response.mp3",
                "size": 1024,
                "last_modified": "2026-01-01T00:00:00Z",
            }
        ],
    )

    response = authenticated_client.get("/api/v1/voice-agent/audio")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["filename"] == "response.mp3"
