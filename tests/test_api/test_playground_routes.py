"""API tests for playground routes."""

from unittest.mock import MagicMock
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


def test_validate_provider_call_id_instantiates_voice_provider(monkeypatch):
    from app.api.v1.routes import playground as playground_routes

    mock_provider = MagicMock()
    mock_provider.retrieve_call_metrics.return_value = {"assistantId": "assistant-1"}
    mock_class = MagicMock(return_value=mock_provider)
    monkeypatch.setattr(playground_routes, "get_voice_provider", lambda _platform: mock_class)

    recording = MagicMock()
    recording.provider_call_id = None
    recording.call_data = {}
    recording.provider_platform = "vapi"

    agent = MagicMock()
    agent.voice_ai_agent_id = "assistant-1"

    playground_routes._validate_provider_call_id_for_recording(
        recording,
        "vapi-call-abc",
        agent,
        "plain-key",
    )

    mock_class.assert_called_once_with(api_key="plain-key")
    mock_provider.retrieve_call_metrics.assert_called_once_with("vapi-call-abc")


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
    monkeypatch.setattr(
        playground_routes,
        "_validate_provider_call_id_for_recording",
        lambda *_args, **_kwargs: None,
    )

    response = authenticated_client.post(
        "/api/v1/playground/call-recordings/654321/refresh",
        json={"provider_call_id": "vapi-call-abc"},
    )

    assert response.status_code == 200
    assert response.json()["message"] == "Call recording refresh initiated"


def test_refresh_rejects_mismatched_provider_call_id(
    authenticated_client,
    make_call_recording,
    make_agent,
    db_session,
    org_id,
):
    integration = Integration(
        id=uuid4(),
        organization_id=org_id,
        platform=IntegrationPlatform.RETELL.value,
        api_key="encrypted-key",
        name="Retell",
        is_active=True,
    )
    db_session.add(integration)
    db_session.flush()
    agent = make_agent(
        voice_ai_integration_id=integration.id,
        voice_ai_agent_id="agent-retell-1",
        call_medium="web_call",
    )
    make_call_recording(
        call_short_id="222333",
        source=CallRecordingSource.PLAYGROUND.value,
        provider_platform=IntegrationPlatform.RETELL.value,
        provider_call_id=None,
        agent_id=agent.id,
        call_data={"call_id": "retell-bound-call"},
    )

    response = authenticated_client.post(
        "/api/v1/playground/call-recordings/222333/refresh",
        json={"provider_call_id": "foreign-call-id"},
    )

    assert response.status_code == 400
    assert "does not match" in response.json()["detail"].lower()


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
