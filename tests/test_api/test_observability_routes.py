"""API tests for observability routes."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
from types import SimpleNamespace
import wave

from app.api.v1.routes import observability

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "elevenlabs"


def _write_wav(path: Path, samples: np.ndarray, sample_rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(samples.astype(np.int16).tobytes())


def test_list_get_delete_observability_calls(authenticated_client, make_call_recording):
    call_recording = make_call_recording(
        call_short_id="654321",
        source="webhook",
        call_data={"messages": [{"role": "user", "content": "hello"}]},
    )

    list_response = authenticated_client.get("/api/v1/observability/calls")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    get_response = authenticated_client.get(f"/api/v1/observability/calls/{call_recording.call_short_id}")
    assert get_response.status_code == 200
    assert get_response.json()["call_short_id"] == "654321"

    delete_response = authenticated_client.delete(
        f"/api/v1/observability/calls/{call_recording.call_short_id}"
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["message"] == "Call deleted"


def test_calls_summary_returns_aggregates(authenticated_client, make_call_recording):
    make_call_recording(
        call_short_id="111111",
        source="webhook",
        call_data={"duration_seconds": 60, "messages": [{"role": "user", "content": "hello"}]},
    )
    make_call_recording(
        call_short_id="222222",
        source="webhook",
        call_data={"duration_seconds": 30, "messages": [{"role": "user", "content": "hi"}]},
    )

    response = authenticated_client.get("/api/v1/observability/calls/summary")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_calls"] == 2
    assert payload["total_minutes"] == 1.5
    assert payload["avg_latency_ms"] == 45000.0
    assert payload["avg_duration_ms"] == 45000.0
    assert payload["trace_available_calls"] == 0


def test_get_call_trace_returns_normalized_payload(
    authenticated_client, make_call_recording, monkeypatch
):
    call_recording = make_call_recording(
        call_short_id="333333",
        source="webhook",
        call_data={
            "messages": [{"role": "user", "content": "hello"}],
            "trace_id": "0af7651916cd43dd8448eb211c80319c",
        },
    )

    async def _mock_query_trace_cloud(trace_id, api_key):
        del api_key
        return {
            "trace_id": trace_id,
            "root_span_id": "root-1",
            "spans": [
                {
                    "span_id": "root-1",
                    "parent_span_id": None,
                    "name": "conversation",
                    "start_time": 1000.0,
                    "end_time": 2000.0,
                    "duration_ms": 1000.0,
                    "attributes": {"conversation.id": "abc"},
                    "status": "ok",
                }
            ],
        }

    monkeypatch.setattr(
        observability,
        "_query_trace_cloud",
        _mock_query_trace_cloud,
    )

    response = authenticated_client.get(
        f"/api/v1/observability/calls/{call_recording.call_short_id}/trace"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["trace_id"] == "0af7651916cd43dd8448eb211c80319c"
    assert payload["root_span_id"] == "root-1"
    assert payload["spans"][0]["name"] == "conversation"


def test_trace_route_returns_404_when_no_trace_id(authenticated_client, make_call_recording):
    call_recording = make_call_recording(
        call_short_id="444444",
        source="webhook",
        call_data={"messages": [{"role": "user", "content": "hello"}]},
    )
    response = authenticated_client.get(
        f"/api/v1/observability/calls/{call_recording.call_short_id}/trace"
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "No trace linked to this call"


def test_get_call_trace_returns_elevenlabs_trace_without_trace_id(
    authenticated_client, make_call_recording, monkeypatch
):
    call_recording = make_call_recording(
        call_short_id="el1111",
        source="webhook",
        provider_platform="elevenlabs",
        provider_call_id="conv_9001k1zph3fkeh5s8xg9z90swaqa",
        call_data={"messages": [{"role": "user", "content": "hello"}]},
    )
    fixture = json.loads((FIXTURE_DIR / "conv_otel.json").read_text())

    async def _mock_query_elevenlabs_trace_for_call(**kwargs):
        del kwargs
        return {
            "trace_id": "0af7651916cd43dd8448eb211c80319c",
            "root_span_id": "1111111111111111",
            "trace_source": "elevenlabs",
            "spans": fixture["otlp_traces"]["resourceSpans"][0]["scopeSpans"][0]["spans"],
        }

    monkeypatch.setattr(
        observability,
        "_query_elevenlabs_trace_for_call",
        _mock_query_elevenlabs_trace_for_call,
    )

    response = authenticated_client.get(
        f"/api/v1/observability/calls/{call_recording.call_short_id}/trace"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["trace_source"] == "elevenlabs"
    assert payload["trace_id"] == "0af7651916cd43dd8448eb211c80319c"


def test_get_call_trace_returns_vapi_synthetic_trace_without_trace_id(
    authenticated_client, make_call_recording
):
    call_recording = make_call_recording(
        call_short_id="vapi44",
        source="webhook",
        provider_platform="vapi",
        provider_call_id="call_vapi_123",
        call_data={
            "id": "call_vapi_123",
            "status": "ended",
            "startedAt": "2026-08-07T09:00:00.000Z",
            "endedAt": "2026-08-07T09:00:10.000Z",
            "messages": [
                {"role": "user", "message": "hello", "secondsFromStart": 0.5, "duration": 900},
                {"role": "assistant", "message": "hi there", "secondsFromStart": 1.6, "duration": 1200},
            ],
            "artifact": {
                "performanceMetrics": {
                    "modelLatencyAverage": 320,
                    "voiceLatencyAverage": 480,
                    "transcriberLatencyAverage": 210,
                    "endpointingLatencyAverage": 140,
                    "turnLatencyAverage": 2200,
                }
            },
        },
    )

    response = authenticated_client.get(
        f"/api/v1/observability/calls/{call_recording.call_short_id}/trace"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["trace_source"] == "vapi_synthetic"
    assert payload["trace_id"] == "vapi-call_vapi_123"
    assert any(span["name"] == "llm" for span in payload["spans"])

    detail = authenticated_client.get(
        f"/api/v1/observability/calls/{call_recording.call_short_id}"
    )
    assert detail.status_code == 200
    provider_trace = detail.json()["call_data"].get("provider_trace")
    assert isinstance(provider_trace, dict)
    assert provider_trace.get("trace_source") == "vapi_synthetic"


def test_get_call_trace_returns_retell_synthetic_trace_without_trace_id(
    authenticated_client, make_call_recording
):
    call_recording = make_call_recording(
        call_short_id="ret444",
        source="webhook",
        provider_platform="retell",
        provider_call_id="call_retell_123",
        call_data={
            "call_id": "call_retell_123",
            "call_status": "ended",
            "start_timestamp": 1_714_423_232_000,
            "end_timestamp": 1_714_423_257_000,
            "transcript_object": [
                {"role": "user", "content": "hello", "words": [{"word": "hello", "start": 0.4, "end": 0.9}]},
                {"role": "agent", "content": "hi there", "words": [{"word": "hi", "start": 1.2, "end": 2.0}]},
            ],
            "latency": {
                "asr": {"p50": 180},
                "llm": {"p50": 420},
                "tts": {"p50": 260},
            },
        },
    )

    response = authenticated_client.get(
        f"/api/v1/observability/calls/{call_recording.call_short_id}/trace"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["trace_source"] == "retell_synthetic"
    assert payload["trace_id"] == "retell-call_retell_123"
    assert any(span["name"] == "stt" for span in payload["spans"])

    detail = authenticated_client.get(
        f"/api/v1/observability/calls/{call_recording.call_short_id}"
    )
    assert detail.status_code == 200
    provider_trace = detail.json()["call_data"].get("provider_trace")
    assert isinstance(provider_trace, dict)
    assert provider_trace.get("trace_source") == "retell_synthetic"


def test_get_call_trace_prefers_stored_provider_trace(authenticated_client, make_call_recording):
    call_recording = make_call_recording(
        call_short_id="stort1",
        source="webhook",
        provider_platform="retell",
        provider_call_id="call_retell_999",
        call_data={
            "provider_trace": {
                "trace_source": "retell_synthetic",
                "normalized_trace": {
                    "trace_id": "retell-call_retell_999",
                    "root_span_id": "root",
                    "spans": [
                        {
                            "span_id": "root",
                            "parent_span_id": None,
                            "name": "conversation",
                            "start_time": 1000.0,
                            "end_time": 2000.0,
                            "duration_ms": 1000.0,
                            "attributes": {"trace.provider": "retell"},
                            "status": "1",
                        }
                    ],
                    "trace_source": "retell_synthetic",
                },
            }
        },
    )

    response = authenticated_client.get(
        f"/api/v1/observability/calls/{call_recording.call_short_id}/trace"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["trace_id"] == "retell-call_retell_999"
    assert payload["trace_source"] == "retell_synthetic"


def test_get_call_trace_returns_404_when_trace_missing_in_store(
    authenticated_client, make_call_recording, monkeypatch
):
    import httpx

    call_recording = make_call_recording(
        call_short_id="555555",
        source="playground",
        call_data={
            "messages": [{"role": "user", "content": "hello"}],
            "trace_id": "0af7651916cd43dd8448eb211c80319c",
        },
    )

    async def _mock_query_trace_tempo(trace_id):
        del trace_id
        request = httpx.Request("GET", "http://tempo/api/traces/test")
        response = httpx.Response(404, request=request)
        raise httpx.HTTPStatusError("not found", request=request, response=response)

    monkeypatch.setattr(observability.settings, "TRACING_QUERY_BACKEND", "tempo")
    monkeypatch.setattr(observability, "_query_trace_tempo", _mock_query_trace_tempo)

    response = authenticated_client.get(
        f"/api/v1/observability/calls/{call_recording.call_short_id}/trace"
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_live_audio_endpoint_serves_partial_wav(
    authenticated_client, make_call_recording, tmp_path
):
    user_path = tmp_path / "user.wav"
    bot_path = tmp_path / "bot.wav"
    samples = np.array([2000, -2000, 2000, -2000], dtype=np.int16)
    _write_wav(user_path, samples)
    _write_wav(bot_path, samples)

    call_recording = make_call_recording(
        call_short_id="777777",
        source="webhook",
        call_event="call_in_progress",
        call_data={
            "live_user_audio_path": str(user_path),
            "live_bot_audio_path": str(bot_path),
            "live_transcript": [],
        },
    )

    response = authenticated_client.get(
        f"/api/v1/observability/calls/{call_recording.call_short_id}/live-audio"
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert float(response.headers["x-audio-duration-sec"]) >= 0
    assert response.content.startswith(b"RIFF")


def test_observability_audio_uses_elevenlabs_proxy(
    authenticated_client, make_integration, make_agent, make_call_recording, monkeypatch
):
    from fastapi.responses import Response

    integration = make_integration(platform="elevenlabs", api_key="encrypted-api-key")
    agent = make_agent(
        integration=integration,
        voice_ai_integration_id=integration.id,
        voice_ai_agent_id="agent_abc",
    )
    call_recording = make_call_recording(
        call_short_id="obsaud",
        source="webhook",
        agent_id=agent.id,
        provider_platform="elevenlabs",
        provider_call_id="conv_123",
        call_data={"recording_urls": {"conversation_audio": "https://api.elevenlabs.io/v1/convai/conversations/conv_123/audio"}},
    )

    def _proxy(**kwargs):
        assert kwargs["call_recording"].call_short_id == "obsaud"
        return Response(content=b"mp3-bytes", media_type="audio/mpeg")

    monkeypatch.setattr(
        "app.services.observability.provider_audio_proxy.stream_elevenlabs_audio_proxy",
        _proxy,
    )

    response = authenticated_client.get(
        f"/api/v1/observability/calls/{call_recording.call_short_id}/audio"
    )
    assert response.status_code == 200
    assert response.content == b"mp3-bytes"
    assert response.headers["content-type"].startswith("audio/mpeg")


def test_webhook_ingest_persists_trace_id(authenticated_client, api_key):
    payload = {
        "id": "provider-call-999",
        "provider_platform": "external",
        "startedAt": "2026-08-07T09:00:00.000Z",
        "endedAt": "2026-08-07T09:01:30.000Z",
        "trace_id": "0af7651916cd43dd8448eb211c80319c",
        "messages": [{"role": "user", "content": "hello"}],
    }
    response = authenticated_client.post(
        f"/api/v1/observability/calls/webhook/{api_key}",
        json=payload,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["trace_id"] == "0af7651916cd43dd8448eb211c80319c"


def test_ingest_elevenlabs_otel_webhook(authenticated_client, api_key):
    payload = json.loads((FIXTURE_DIR / "post_call_transcription_otel.json").read_text())
    response = authenticated_client.post(
        f"/api/v1/observability/calls/webhook/elevenlabs/{api_key}",
        json=payload,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["provider_platform"] == "elevenlabs"
    assert body["provider_call_id"] == payload["data"]["conversation_id"]
    assert body["call_data"]["provider_trace"]["source"] == "elevenlabs_post_call_webhook"


def test_observe_endpoint_persists_trace_id(authenticated_client):
    payload = {
        "id": "observe-call-999",
        "provider_platform": "retell",
        "startedAt": "2026-08-07T09:00:00.000Z",
        "endedAt": "2026-08-07T09:01:30.000Z",
        "trace_id": "0af7651916cd43dd8448eb211c80319c",
        "messages": [{"role": "assistant", "content": "hello"}],
    }
    response = authenticated_client.post("/api/v1/observability/observe", json=payload)
    assert response.status_code == 201
    body = response.json()
    assert body["provider_call_id"] == "observe-call-999"
    assert body["trace_id"] == "0af7651916cd43dd8448eb211c80319c"


def test_refresh_observability_call_pulls_provider_metrics(
    authenticated_client, make_integration, make_agent, make_call_recording, monkeypatch
):
    integration = make_integration(platform="vapi", api_key="encrypted-api-key")
    agent = make_agent(integration=integration, voice_ai_integration_id=integration.id)
    call_recording = make_call_recording(
        call_short_id="obsrf1",
        source="webhook",
        agent_id=agent.id,
        provider_platform="vapi",
        provider_call_id="call_123",
        call_data={"status": "queued"},
    )

    class _Provider:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def retrieve_call_metrics(self, call_id):
            assert call_id == "call_123"
            return {"id": "call_123", "status": "ended", "messages": [{"role": "assistant", "message": "done"}]}

    monkeypatch.setattr(observability, "decrypt_api_key", lambda _v: "decrypted")
    monkeypatch.setattr(observability, "get_voice_provider", lambda _p: _Provider)

    response = authenticated_client.post(f"/api/v1/observability/calls/{call_recording.call_short_id}/refresh")
    assert response.status_code == 200
    payload = response.json()
    assert payload["call_data"]["status"] == "ended"
    assert payload["provider_platform"] == "vapi"


def test_refresh_observability_call_requires_provider_info(
    authenticated_client, make_call_recording
):
    call_recording = make_call_recording(
        call_short_id="obsrf2",
        source="webhook",
        call_data={"status": "queued"},
        provider_platform=None,
        provider_call_id=None,
    )

    response = authenticated_client.post(f"/api/v1/observability/calls/{call_recording.call_short_id}/refresh")
    assert response.status_code == 400
    assert "provider information" in response.json()["detail"].lower()


def test_vapi_webhook_terminal_event_triggers_refresh_fallback(
    authenticated_client, api_key, make_integration, make_agent, monkeypatch
):
    integration = make_integration(platform="vapi", api_key="encrypted-api-key")
    agent = make_agent(
        integration=integration,
        voice_ai_integration_id=integration.id,
        voice_ai_agent_id="assist_123",
    )

    monkeypatch.setattr(observability, "decrypt_api_key", lambda _v: "decrypted")

    class _Provider:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def retrieve_call_metrics(self, call_id):
            assert call_id == "call_vapi_terminal"
            return {
                "id": call_id,
                "status": "ended",
                "analysis": {"summary": "Complete"},
                "costBreakdown": {"transport": 0.001},
                "artifact": {"messages": [{"role": "assistant", "message": "done"}]},
            }

    monkeypatch.setattr(observability, "get_voice_provider", lambda _p: _Provider)

    payload = {
        "id": "call_vapi_terminal",
        "agent_id": "assist_123",
        "status": "ended",
        "messages": [],
    }
    response = authenticated_client.post(
        f"/api/v1/observability/calls/webhook/vapi/{api_key}",
        json=payload,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["call_event"] == "call_ended"
    assert body["call_data"]["status"] == "ended"
    assert body["call_data"]["analysis"]["summary"] == "Complete"


def test_retell_webhook_terminal_event_triggers_refresh_fallback(
    authenticated_client, api_key, make_integration, make_agent, monkeypatch
):
    integration = make_integration(platform="retell", api_key="encrypted-api-key")
    agent = make_agent(
        integration=integration,
        voice_ai_integration_id=integration.id,
        voice_ai_agent_id="agent_retell_123",
    )

    monkeypatch.setattr(observability, "decrypt_api_key", lambda _v: "decrypted")

    class _Provider:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def retrieve_call_metrics(self, call_id):
            assert call_id == "call_retell_terminal"
            return {
                "call_id": call_id,
                "call_status": "ended",
                "call_analysis": {"call_summary": "Resolved"},
                "call_cost": {"combined_cost": 0.0123},
                "transcript_object": [{"role": "agent", "content": "done"}],
            }

    monkeypatch.setattr(observability, "get_voice_provider", lambda _p: _Provider)

    payload = {
        "event": "call_analyzed",
        "call": {
            "call_id": "call_retell_terminal",
            "agent_id": "agent_retell_123",
            "call_status": "ended",
        },
    }
    response = authenticated_client.post(
        f"/api/v1/observability/calls/webhook/retell/{api_key}",
        json=payload,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["call_event"] == "call_ended"
    assert body["call_data"]["call_status"] == "ended"
    assert body["call_data"]["call_analysis"]["call_summary"] == "Resolved"


def test_webhook_call_ended_auto_queues_evaluation(
    authenticated_client,
    api_key,
    make_agent,
    make_evaluator,
    db_session,
    monkeypatch,
):
    agent = make_agent()
    evaluator = make_evaluator(
        agent_id=agent.id,
        workspace_id=agent.workspace_id,
    )
    agent.observability_auto_evaluator_id = evaluator.id
    db_session.commit()

    monkeypatch.setattr(
        observability.process_evaluator_result_task,
        "delay",
        lambda _result_id: SimpleNamespace(id="task-123"),
    )

    payload = {
        "id": "provider-call-auto",
        "provider_platform": "external",
        "agent_id": str(agent.id),
        "startedAt": "2026-08-07T09:00:00.000Z",
        "endedAt": "2026-08-07T09:01:30.000Z",
        "messages": [{"role": "user", "content": "hello"}],
    }
    ingest_response = authenticated_client.post(
        f"/api/v1/observability/calls/webhook/{api_key}",
        json=payload,
    )
    assert ingest_response.status_code == 201
    call_short_id = ingest_response.json()["call_short_id"]

    detail_response = authenticated_client.get(f"/api/v1/observability/calls/{call_short_id}")
    assert detail_response.status_code == 200
    assert detail_response.json()["evaluator_result_id"] is not None


def test_live_event_ingest_is_idempotent_and_issues_trace_id(authenticated_client, monkeypatch):
    monkeypatch.setattr(observability.settings, "OBSERVABILITY_LIVE_INGEST_ENABLED", True)
    monkeypatch.setattr(observability.settings, "OBSERVABILITY_LIVE_EVENT_MAX_TS_DRIFT_SECONDS", 999999999)
    now_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    payload = {
        "event_id": "evt_live_001",
        "call_id": "lk_call_001",
        "event_type": "call.started",
        "seq": 1,
        "event_ts": now_iso,
        "platform": "livekit",
        "payload": {"startedAt": now_iso},
    }

    first = authenticated_client.post("/api/v1/observability/live/events", json=payload)
    assert first.status_code == 202
    first_body = first.json()
    assert first_body["accepted"] is True
    assert first_body["duplicate"] is False
    assert isinstance(first_body["trace_id"], str)
    assert len(first_body["trace_id"]) == 32

    second = authenticated_client.post("/api/v1/observability/live/events", json=payload)
    assert second.status_code == 202
    second_body = second.json()
    assert second_body["accepted"] is True
    assert second_body["duplicate"] is True
    assert second_body["call_short_id"] == first_body["call_short_id"]


def test_live_event_ingest_rejects_stale_sequence(authenticated_client, monkeypatch):
    monkeypatch.setattr(observability.settings, "OBSERVABILITY_LIVE_INGEST_ENABLED", True)
    monkeypatch.setattr(observability.settings, "OBSERVABILITY_LIVE_EVENT_MAX_OUT_OF_ORDER_SEQ", 2)
    monkeypatch.setattr(observability.settings, "OBSERVABILITY_LIVE_EVENT_MAX_TS_DRIFT_SECONDS", 999999999)
    base_ts = datetime.now(UTC)
    first = {
        "event_id": "evt_live_100",
        "call_id": "pc_call_100",
        "event_type": "turn.user",
        "seq": 10,
        "event_ts": base_ts.isoformat().replace("+00:00", "Z"),
        "platform": "pipecat",
        "payload": {"content": "hello"},
    }
    stale = {
        "event_id": "evt_live_101",
        "call_id": "pc_call_100",
        "event_type": "turn.assistant",
        "seq": 2,
        "event_ts": (base_ts + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
        "platform": "pipecat",
        "payload": {"content": "hi"},
    }
    first_resp = authenticated_client.post("/api/v1/observability/live/events", json=first)
    assert first_resp.status_code == 202
    stale_resp = authenticated_client.post("/api/v1/observability/live/events", json=stale)
    assert stale_resp.status_code == 409


def test_live_latency_metrics_endpoints(authenticated_client, monkeypatch, make_agent):
    monkeypatch.setattr(observability.settings, "OBSERVABILITY_LIVE_INGEST_ENABLED", True)
    monkeypatch.setattr(observability.settings, "OBSERVABILITY_LIVE_AGGREGATES_ENABLED", True)
    monkeypatch.setattr(observability.settings, "OBSERVABILITY_LIVE_EVENT_MAX_TS_DRIFT_SECONDS", 999999999)
    agent = make_agent()

    base_ts = datetime.now(UTC)
    events = [
        {
            "event_id": "evt_lat_1",
            "call_id": "lk_latency_call",
            "event_type": "turn.user",
            "seq": 1,
            "event_ts": base_ts.isoformat().replace("+00:00", "Z"),
            "platform": "livekit",
            "agent_ref": str(agent.id),
            "payload": {"content": "hello", "latency": {"llm": 200, "tts": 150}},
        },
        {
            "event_id": "evt_lat_2",
            "call_id": "lk_latency_call",
            "event_type": "turn.assistant",
            "seq": 2,
            "event_ts": (base_ts + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
            "platform": "livekit",
            "agent_ref": str(agent.id),
            "payload": {"content": "hi", "latency": {"llm": 500, "tts": 320}},
        },
    ]
    for item in events:
        resp = authenticated_client.post("/api/v1/observability/live/events", json=item)
        assert resp.status_code == 202

    metrics_resp = authenticated_client.get("/api/v1/observability/live/metrics/latency")
    assert metrics_resp.status_code == 200
    metrics_body = metrics_resp.json()
    assert metrics_body["windows"]["300s"]["sample_count"] >= 2
    assert "llm_ms" in metrics_body["windows"]["300s"]["metrics"]

    agent_metrics = authenticated_client.get(
        f"/api/v1/observability/live/agents/{agent.id}/latency"
    )
    assert agent_metrics.status_code == 200
    agent_body = agent_metrics.json()
    assert agent_body["scope"] == "agent"
    assert agent_body["agent_id"] == str(agent.id)


def test_live_event_ingest_records_slo_breach(authenticated_client, monkeypatch):
    monkeypatch.setattr(observability.settings, "OBSERVABILITY_LIVE_INGEST_ENABLED", True)
    monkeypatch.setattr(observability.settings, "OBSERVABILITY_LIVE_AGGREGATES_ENABLED", True)
    monkeypatch.setattr(observability.settings, "OBSERVABILITY_LIVE_SLO_ALERTS_ENABLED", True)
    monkeypatch.setattr(observability.settings, "OBSERVABILITY_LIVE_SLO_MIN_SAMPLE_COUNT", 1)
    monkeypatch.setattr(observability.settings, "OBSERVABILITY_LIVE_SLO_P90_LLM_MS", 100)
    monkeypatch.setattr(observability.settings, "OBSERVABILITY_LIVE_EVENT_MAX_TS_DRIFT_SECONDS", 999999999)

    now_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    payload = {
        "event_id": "evt_slo_1",
        "call_id": "live_call_slo_1",
        "event_type": "turn.assistant",
        "seq": 1,
        "event_ts": now_iso,
        "platform": "livekit",
        "payload": {"content": "hello", "latency": {"llm": 450}},
    }
    response = authenticated_client.post("/api/v1/observability/live/events", json=payload)
    assert response.status_code == 202
    assert response.json()["slo_breach_detected"] is True


def test_get_call_trace_returns_pipecat_live_synthetic_trace(
    authenticated_client, make_call_recording
):
    trace_id = "60e7082206844a85bbd9eaa13888c5ed"
    call_recording = make_call_recording(
        call_short_id="pipe77",
        source="webhook",
        provider_platform="pipecat",
        provider_call_id="pipecat-live-1786946667",
        trace_id=trace_id,
        call_data={
            "trace_id": trace_id,
            "startedAt": "2026-08-17T06:04:27.000Z",
            "endedAt": "2026-08-17T06:04:48.000Z",
            "status": "ended",
            "live_transcript": [
                {
                    "role": "user",
                    "content": "Hello, can you hear me?",
                    "event_ts": "2026-08-17T06:04:30.641055+00:00",
                },
                {
                    "role": "assistant",
                    "content": "Yes, I can hear you clearly.",
                    "event_ts": "2026-08-17T06:04:33.708357+00:00",
                    "latency": {"llm_ms": 380, "tts_ms": 210},
                },
            ],
        },
    )

    response = authenticated_client.get(
        f"/api/v1/observability/calls/{call_recording.call_short_id}/trace"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["trace_source"] == "pipecat_live_synthetic"
    assert payload["trace_id"] == trace_id
    assert any(span["name"] == "llm" for span in payload["spans"])
    assert any(span["name"] == "tts" for span in payload["spans"])

    detail = authenticated_client.get(
        f"/api/v1/observability/calls/{call_recording.call_short_id}"
    )
    assert detail.status_code == 200
    provider_trace = detail.json()["call_data"].get("provider_trace")
    assert isinstance(provider_trace, dict)
    assert provider_trace.get("trace_source") == "pipecat_live_synthetic"


def test_live_event_ingest_persists_synthetic_trace_on_call_end(authenticated_client, monkeypatch):
    monkeypatch.setattr(observability.settings, "OBSERVABILITY_LIVE_INGEST_ENABLED", True)
    monkeypatch.setattr(observability.settings, "OBSERVABILITY_LIVE_EVENT_MAX_TS_DRIFT_SECONDS", 999999999)
    call_id = "pipecat-live-end-1"
    base_ts = datetime.now(UTC)

    events = [
        {
            "event_id": "evt_live_end_1",
            "call_id": call_id,
            "event_type": "call.started",
            "seq": 1,
            "event_ts": base_ts.isoformat().replace("+00:00", "Z"),
            "platform": "pipecat",
            "payload": {"startedAt": base_ts.isoformat().replace("+00:00", "Z")},
        },
        {
            "event_id": "evt_live_end_2",
            "call_id": call_id,
            "event_type": "turn.assistant",
            "seq": 2,
            "event_ts": (base_ts + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
            "platform": "pipecat",
            "payload": {"content": "hello", "latency": {"llm_ms": 300, "tts_ms": 150}},
        },
        {
            "event_id": "evt_live_end_3",
            "call_id": call_id,
            "event_type": "call.ended",
            "seq": 3,
            "event_ts": (base_ts + timedelta(seconds=2)).isoformat().replace("+00:00", "Z"),
            "platform": "pipecat",
            "payload": {"endedAt": (base_ts + timedelta(seconds=2)).isoformat().replace("+00:00", "Z")},
        },
    ]

    call_short_id = None
    for item in events:
        resp = authenticated_client.post("/api/v1/observability/live/events", json=item)
        assert resp.status_code == 202
        call_short_id = resp.json()["call_short_id"]

    trace_resp = authenticated_client.get(f"/api/v1/observability/calls/{call_short_id}/trace")
    assert trace_resp.status_code == 200
    trace_payload = trace_resp.json()
    assert trace_payload["trace_source"] == "pipecat_live_synthetic"
    assert any(span["name"] == "llm" for span in trace_payload["spans"])
