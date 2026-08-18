from app.services.observability.vapi_trace import build_vapi_synthetic_trace


def test_build_vapi_synthetic_trace_builds_turn_and_metric_spans():
    call_data = {
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
    }

    payload = build_vapi_synthetic_trace(call_data, provider_call_id="call_vapi_123")

    assert payload is not None
    assert payload["trace_source"] == "vapi_synthetic"
    assert payload["trace_id"] == "vapi-call_vapi_123"
    names = [span["name"] for span in payload["spans"]]
    assert "conversation" in names
    assert "turn" in names
    assert "stt" in names
    assert "llm" in names
    assert "tts" in names
