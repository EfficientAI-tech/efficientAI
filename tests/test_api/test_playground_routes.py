"""API tests for playground routes."""


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


def test_download_playground_recording_audio_prefers_vapi_presigned_url(monkeypatch):
    from app.api.v1.routes.playground import _download_playground_recording_audio

    captured = {}

    class FakeResp:
        status_code = 200
        content = b"audio-bytes"
        headers = {"content-type": "audio/wav"}

    def fake_get(url, headers=None, timeout=120):
        captured["url"] = url
        captured["headers"] = headers
        return FakeResp()

    monkeypatch.setattr("requests.get", fake_get)

    call_data = {
        "artifact": {
            "presignedMonoUrl": "https://storage.example.com/mono.wav?X-Amz-Signature=abc",
            "recordingUrl": "https://storage.example.com/raw-mono.wav",
        }
    }
    audio_bytes, resp = _download_playground_recording_audio(call_data, "vapi", "vapi-secret")

    assert audio_bytes == b"audio-bytes"
    assert captured["url"] == "https://storage.example.com/mono.wav?X-Amz-Signature=abc"
    assert captured["headers"] is None


def test_download_playground_recording_audio_uses_vapi_bearer_for_non_presigned(monkeypatch):
    from app.api.v1.routes.playground import _download_playground_recording_audio

    captured = {}

    class FakeResp:
        status_code = 200
        content = b"audio-bytes"
        headers = {"content-type": "audio/mpeg"}

    def fake_get(url, headers=None, timeout=120):
        captured["headers"] = headers
        return FakeResp()

    monkeypatch.setattr("requests.get", fake_get)

    call_data = {"recordingUrl": "https://api.vapi.ai/recording.wav"}
    _download_playground_recording_audio(call_data, "vapi", "vapi-secret")

    assert captured["headers"] == {"Authorization": "Bearer vapi-secret"}


def test_refresh_call_recording_queues_evaluation_without_result(
    authenticated_client,
    make_agent,
    make_integration,
    make_call_recording,
    monkeypatch,
):
    from app.models.enums import IntegrationPlatform

    integration = make_integration(
        platform=IntegrationPlatform.VAPI.value,
        api_key="enc",
    )
    agent = make_agent(integration=integration)
    make_call_recording(
        call_short_id="464643",
        source="playground",
        provider_platform="vapi",
        provider_call_id="vapi-call-1",
        agent_id=agent.id,
        call_data={"status": "ended"},
    )

    queued = []

    def fake_poll(*args, **kwargs):
        queued.append(args)

    monkeypatch.setattr("app.api.v1.routes.playground.poll_call_metrics", fake_poll)
    monkeypatch.setattr(
        "app.services.playground.post_call_processing.refresh_call_metrics_sync",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr("app.core.encryption.decrypt_api_key", lambda _key: "vapi-secret")

    response = authenticated_client.post("/api/v1/playground/call-recordings/464643/refresh")

    assert response.status_code == 200
    body = response.json()
    assert body["evaluation_queued"] is True
    assert len(queued) == 1


def test_list_playground_call_recordings(authenticated_client, make_call_recording):
    make_call_recording(call_short_id="111111", source="playground", call_data={"foo": "bar"})

    response = authenticated_client.get("/api/v1/playground/call-recordings")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["call_short_id"] == "111111"
