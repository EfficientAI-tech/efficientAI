from app.services.observability.retell_trace import build_retell_synthetic_trace


def test_build_retell_synthetic_trace_builds_turn_and_metric_spans():
    call_data = {
        "call_id": "call_retell_123",
        "call_status": "ended",
        "start_timestamp": 1_714_423_232_000,
        "end_timestamp": 1_714_423_257_000,
        "duration_ms": 25000,
        "transcript_object": [
            {
                "role": "user",
                "content": "Hello",
                "words": [{"word": "Hello", "start": 0.5, "end": 1.0}],
            },
            {
                "role": "agent",
                "content": "Hi there",
                "words": [{"word": "Hi", "start": 1.4, "end": 1.6}, {"word": "there", "start": 1.6, "end": 2.0}],
            },
        ],
        "latency": {
            "asr": {"p50": 180, "p90": 240},
            "llm": {"p50": 420, "p90": 510},
            "tts": {"p50": 260, "p90": 320},
            "e2e": {"p50": 980, "p90": 1200},
        },
    }

    payload = build_retell_synthetic_trace(call_data, provider_call_id="call_retell_123")

    assert payload is not None
    assert payload["trace_source"] == "retell_synthetic"
    assert payload["trace_id"] == "retell-call_retell_123"
    names = [span["name"] for span in payload["spans"]]
    assert "conversation" in names
    assert "turn" in names
    assert "stt" in names
    assert "llm" in names
    assert "tts" in names

    user_turn = next(
        span for span in payload["spans"] if span["name"] == "turn" and span["attributes"].get("turn.role") == "user"
    )
    assert user_turn["attributes"]["turn.user_transcript"] == "Hello"
    assert user_turn["start_time"] == 1_714_423_232_000 + 500


def test_build_retell_synthetic_trace_parses_plain_text_transcript():
    call_data = {
        "call_id": "call_retell_text",
        "transcript": "User: Need help\nAgent: Sure thing",
        "latency": {"llm": {"p50": 300}},
    }

    payload = build_retell_synthetic_trace(call_data, provider_call_id="call_retell_text")

    assert payload is not None
    turn_spans = [span for span in payload["spans"] if span["name"] == "turn"]
    assert len(turn_spans) == 2
