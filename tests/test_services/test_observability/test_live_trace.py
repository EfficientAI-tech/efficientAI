from app.services.observability.live_trace import build_live_synthetic_trace


def test_build_live_synthetic_trace_builds_turn_and_metric_spans():
    call_data = {
        "trace_id": "abc123trace456",
        "startedAt": "2026-08-17T06:04:27.000Z",
        "endedAt": "2026-08-17T06:04:48.000Z",
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
    }

    payload = build_live_synthetic_trace(
        call_data,
        provider_call_id="pipecat-live-1",
        provider_platform="pipecat",
    )

    assert payload is not None
    assert payload["trace_source"] == "pipecat_live_synthetic"
    assert payload["trace_id"] == "abc123trace456"
    names = [span["name"] for span in payload["spans"]]
    assert "conversation" in names
    assert names.count("turn") == 2
    assert "llm" in names
    assert "tts" in names

    llm_turn_span = next(
        span
        for span in payload["spans"]
        if span["name"] == "llm" and span["attributes"].get("metric.scope") == "turn_reported"
    )
    assert llm_turn_span["duration_ms"] == 380


def test_build_live_synthetic_trace_returns_none_without_transcript():
    assert build_live_synthetic_trace({}, provider_call_id="x", provider_platform="pipecat") is None
