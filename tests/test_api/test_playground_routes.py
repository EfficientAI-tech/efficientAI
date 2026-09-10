"""API tests for playground routes."""

from uuid import uuid4

from app.models.database import CallRecordingSource, Integration, IntegrationPlatform


def test_extract_transcript_from_smallest_call_data():
    from app.api.v1.routes.playground import extract_transcript_from_call_data

    transcript_text, segments = extract_transcript_from_call_data(
        {
            "transcript_object": [
                {"speaker": "User", "text": "hello", "start": 0.0, "end": 0.4},
                {"speaker": "Agent", "text": "hi", "start": 0.6, "end": 1.0},
            ]
        },
        "smallest",
    )

    assert transcript_text == "User: hello\nAgent: hi"
    assert len(segments) == 2
    assert segments[0]["speaker"] == "User"


def test_list_playground_call_recordings(authenticated_client, make_call_recording):
    make_call_recording(call_short_id="111111", source="playground", call_data={"foo": "bar"})

    response = authenticated_client.get("/api/v1/playground/call-recordings")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["call_short_id"] == "111111"


def test_refresh_call_recording_accepts_inline_provider_call_id(
    authenticated_client,
    make_call_recording,
    make_agent,
    db_session,
    org_id,
    monkeypatch,
):
    from app.api.v1.routes import playground as playground_routes

    integration = Integration(
        id=uuid4(),
        organization_id=org_id,
        platform=IntegrationPlatform.VAPI.value,
        api_key="encrypted-key",
        name="Vapi",
        is_active=True,
    )
    db_session.add(integration)
    db_session.flush()
    agent = make_agent(
        voice_ai_integration_id=integration.id,
        voice_ai_agent_id="assistant-1",
        call_medium="web_call",
    )
    make_call_recording(
        call_short_id="654321",
        source=CallRecordingSource.PLAYGROUND.value,
        provider_platform=IntegrationPlatform.VAPI.value,
        provider_call_id=None,
        agent_id=agent.id,
    )

    monkeypatch.setattr(playground_routes, "decrypt_api_key", lambda _key: "plain-key")
    monkeypatch.setattr(playground_routes, "poll_call_metrics", lambda *_args, **_kwargs: None)

    response = authenticated_client.post(
        "/api/v1/playground/call-recordings/654321/refresh",
        json={"provider_call_id": "vapi-call-abc"},
    )

    assert response.status_code == 200
    assert response.json()["message"] == "Call recording refresh initiated"


def test_refresh_call_recording_without_provider_info_returns_400(
    authenticated_client,
    make_call_recording,
):
    make_call_recording(
        call_short_id="000001",
        source=CallRecordingSource.PLAYGROUND.value,
        provider_platform=None,
        provider_call_id=None,
    )

    response = authenticated_client.post(
        "/api/v1/playground/call-recordings/000001/refresh",
    )

    assert response.status_code == 400
    assert "provider" in response.json()["detail"].lower()
