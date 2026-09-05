"""Tests for synthetic trace OTLP mapping."""

from app.services.synthetic_traces.otlp_mapper import (
    compute_trace_latency_summary,
    derive_turns_from_spans,
    extract_correlation_ids,
    filter_spans_for_trace,
    merge_tier1_and_otel_turns,
)


def test_derive_turns_from_spans_extracts_component_ttfb():
    spans = [
        {
            "name": "turn",
            "span_id": "turn-1",
            "attributes": {"turn.number": 1},
        },
        {
            "name": "stt",
            "span_id": "stt-1",
            "attributes": {
                "turn.number": 1,
                "gen_ai.operation.name": "stt",
                "metrics.ttfb": 0.12,
                "transcript": "hello",
            },
        },
        {
            "name": "llm",
            "span_id": "llm-1",
            "attributes": {
                "turn.number": 1,
                "gen_ai.operation.name": "chat",
                "metrics.ttfb": 0.45,
            },
        },
        {
            "name": "tts",
            "span_id": "tts-1",
            "attributes": {
                "turn.number": 1,
                "gen_ai.operation.name": "tts",
                "metrics.ttfb": 0.08,
            },
        },
    ]
    turns = derive_turns_from_spans(spans)
    assert len(turns) == 1
    assert turns[0]["turn_number"] == 1
    assert turns[0]["stt_ttfb_ms"] == 120.0
    assert turns[0]["llm_ttfb_ms"] == 450.0
    assert turns[0]["tts_ttfb_ms"] == 80.0
    assert turns[0]["transcript"] == "User: hello"


def test_derive_turns_from_pipecat_parent_child_spans():
    """Pipecat turn spans carry turn.number; children link via parent_span_id."""
    spans = [
        {
            "name": "turn",
            "span_id": "turn-2",
            "attributes": {
                "turn.number": 2,
                "turn.duration_seconds": 10.239,
                "turn.user_bot_latency_seconds": 4.5,
            },
        },
        {
            "name": "llm_response",
            "span_id": "llm-2",
            "parent_span_id": "turn-2",
            "attributes": {"metrics.ttfb": 3.958},
        },
        {
            "name": "stt",
            "span_id": "stt-2",
            "parent_span_id": "turn-2",
            "start_time_unix_nano": 0,
            "end_time_unix_nano": 17_161_000_000,
            "attributes": {"metrics.ttfb": 0},
        },
    ]
    turns = derive_turns_from_spans(spans)
    assert len(turns) == 1
    assert turns[0]["turn_number"] == 1
    assert turns[0]["llm_ttfb_ms"] == 3958.0
    assert turns[0].get("stt_ttfb_ms") is None
    assert turns[0]["sut_response_latency_ms"] == 4500.0
    assert turns[0]["tts_ttfb_ms"] == 542.0
    assert turns[0]["extra"]["turn_duration_seconds"] == 10.239


def test_compute_trace_latency_summary_uses_sut_then_llm_fallback():
    turns = [
        {
            "turn_number": 1,
            "sut_response_latency_ms": 1000.0,
            "llm_ttfb_ms": 400.0,
            "extra": {"user_text": "one"},
        },
        {
            "turn_number": 2,
            "sut_response_latency_ms": 2000.0,
            "llm_ttfb_ms": 800.0,
            "extra": {"user_text": "two"},
        },
        {
            "turn_number": 3,
            "sut_response_latency_ms": 3000.0,
            "llm_ttfb_ms": 1200.0,
            "extra": {"user_text": "three"},
        },
    ]
    summary = compute_trace_latency_summary(turns)
    assert summary["turn_count"] == 3
    assert summary["response_latency_p50_ms"] == 2000.0
    assert summary["response_latency_p90_ms"] == 3000.0
    assert summary["component_aggregates"]["llm_ttfb_ms"]["p50"] == 800.0


def test_compute_trace_latency_summary_ignores_agent_only_openers():
    turns = [
        {
            "turn_number": 1,
            "sut_response_latency_ms": 9000.0,
            "llm_ttfb_ms": 9000.0,
            "extra": {"assistant_text": "Welcome"},
        },
        {
            "turn_number": 2,
            "sut_response_latency_ms": 1200.0,
            "extra": {"user_text": "hello"},
        },
        {
            "turn_number": 3,
            "sut_response_latency_ms": 2400.0,
            "extra": {"user_text": "bye"},
        },
    ]
    summary = compute_trace_latency_summary(turns)
    assert summary["response_latency_p50_ms"] == 1200.0


def test_finalize_turn_derives_sut_from_stt_llm_tts_for_user_turn():
    spans = [
        {
            "name": "stt",
            "span_id": "stt-1",
            "start_time_unix_nano": 100,
            "attributes": {
                "gen_ai.operation.name": "stt",
                "metrics.ttfb": 0.12,
                "transcript": "hello",
            },
        },
        {
            "name": "llm_response",
            "span_id": "llm-1",
            "start_time_unix_nano": 200,
            "attributes": {"metrics.ttfb": 0.45, "output": "Hi"},
        },
        {
            "name": "tts",
            "span_id": "tts-1",
            "start_time_unix_nano": 300,
            "attributes": {
                "gen_ai.operation.name": "tts",
                "metrics.ttfb": 0.08,
                "text": "Hi",
            },
        },
    ]
    turns = derive_turns_from_spans(spans)
    assert len(turns) == 1
    assert turns[0]["sut_response_latency_ms"] == 650.0
    assert turns[0]["extra"]["sut_derived_from_components"] is True


def test_response_latency_excludes_partial_llm_only_user_turn():
    turns = [
        {
            "turn_number": 1,
            "sut_response_latency_ms": 400.0,
            "llm_ttfb_ms": 400.0,
            "extra": {"user_text": "hi", "sut_is_partial_fallback": True},
        },
        {
            "turn_number": 2,
            "sut_response_latency_ms": 1200.0,
            "extra": {"user_text": "bye"},
        },
    ]
    from app.services.synthetic_traces.otlp_mapper import response_latency_samples

    assert response_latency_samples(turns) == [1200.0]


def test_compute_trace_latency_summary_includes_measured_greeting_opener():
    """TDD §9.3 worked example includes greeting turn when Pipecat measured e2e."""
    turns = [
        {
            "turn_number": 1,
            "sut_response_latency_ms": 800.0,
            "extra": {"assistant_text": "Welcome", "sut_measured_e2e": True},
        },
        {
            "turn_number": 2,
            "sut_response_latency_ms": 920.0,
            "extra": {"user_text": "hello"},
        },
        {
            "turn_number": 3,
            "sut_response_latency_ms": 1100.0,
            "extra": {"user_text": "more"},
        },
        {
            "turn_number": 4,
            "sut_response_latency_ms": 1400.0,
            "extra": {"user_text": "bye"},
        },
    ]
    summary = compute_trace_latency_summary(turns)
    assert summary["response_latency_sample_count"] == 4
    assert summary["response_latency_p50_ms"] == 1100.0
    assert summary["response_latency_p90_ms"] == 1400.0
    assert summary["response_latency_p95_ms"] == 1400.0


def test_consolidate_turn_rows_merges_adjacent_same_sut():
    from app.services.synthetic_traces.otlp_mapper import _consolidate_turn_rows

    turns = [
        {
            "stt_ttfb_ms": 580.0,
            "llm_ttfb_ms": 3686.0,
            "tts_ttfb_ms": 190.0,
            "sut_response_latency_ms": 5306.0,
            "extra": {"user_text": "help", "assistant_text": "Sure", "_span_ids": ["a", "b", "c"]},
        },
        {
            "llm_ttfb_ms": 5306.0,
            "tts_ttfb_ms": 190.0,
            "sut_response_latency_ms": 5306.0,
            "extra": {"assistant_text": "Sure", "_span_ids": ["b", "c"]},
        },
    ]
    merged = _consolidate_turn_rows(turns)
    assert len(merged) == 1


def test_consolidate_turn_rows_merges_same_sut_bot_fragment():
    """WebRTC multi-agent calls may emit user+bot rows plus orphan bot row with same e2e."""
    from app.services.synthetic_traces.otlp_mapper import _consolidate_turn_rows

    turns = [
        {
            "turn_number": 1,
            "stt_ttfb_ms": 580.0,
            "llm_ttfb_ms": 3686.0,
            "tts_ttfb_ms": 190.0,
            "sut_response_latency_ms": 5306.0,
            "extra": {
                "user_text": "Need help",
                "assistant_text": "Sure.",
                "_span_ids": ["stt-1", "llm-1", "tts-1"],
            },
        },
        {
            "turn_number": 2,
            "llm_ttfb_ms": 5306.0,
            "tts_ttfb_ms": 190.0,
            "sut_response_latency_ms": 5306.0,
            "extra": {
                "assistant_text": "Sure.",
                "_span_ids": ["llm-1", "tts-1"],
            },
        },
    ]
    merged = _consolidate_turn_rows(turns)
    assert len(merged) == 1
    assert merged[0]["stt_ttfb_ms"] == 580.0
    assert merged[0]["llm_ttfb_ms"] == 5306.0
    assert merged[0]["sut_response_latency_ms"] == 5306.0


def test_apply_turn_span_metadata_matches_by_time_not_index():
    spans = [
        {
            "name": "llm_response",
            "span_id": "llm-greet",
            "start_time_unix_nano": 100,
            "attributes": {"metrics.ttfb": 1.5, "output": "Welcome!"},
        },
        {
            "name": "stt",
            "span_id": "stt-user",
            "start_time_unix_nano": 5_000_000_000,
            "attributes": {
                "gen_ai.operation.name": "stt",
                "metrics.ttfb": 0.4,
                "transcript": "Need help",
            },
        },
        {
            "name": "llm_response",
            "span_id": "llm-reply",
            "start_time_unix_nano": 6_000_000_000,
            "attributes": {"metrics.ttfb": 2.1, "output": "Sure thing."},
        },
        {
            "name": "turn",
            "span_id": "turn-user",
            "start_time_unix_nano": 4_900_000_000,
            "end_time_unix_nano": 8_000_000_000,
            "attributes": {"turn.user_bot_latency_seconds": 3.2},
        },
        {
            "name": "turn",
            "span_id": "turn-greet",
            "start_time_unix_nano": 50,
            "end_time_unix_nano": 2_000_000_000,
            "attributes": {"turn.user_bot_latency_seconds": 0.8},
        },
    ]
    turns = derive_turns_from_spans(spans)
    assert len(turns) == 2
    assert turns[0]["sut_response_latency_ms"] == 800.0
    assert turns[0]["extra"].get("sut_measured_e2e") is True
    assert turns[1]["sut_response_latency_ms"] == 3200.0
    assert "Need help" in turns[1]["extra"]["user_text"]


def test_derive_turns_renumbers_duplicate_pipecat_turn_one_spans():
    """Pipecat may emit multiple turn spans numbered 1 (intro + user turn)."""
    spans = [
        {
            "name": "turn",
            "span_id": "turn-intro",
            "start_time_unix_nano": 100,
            "attributes": {"turn.number": 1},
        },
        {
            "name": "llm_response",
            "span_id": "llm-intro",
            "parent_span_id": "turn-intro",
            "attributes": {"metrics.ttfb": 1.551},
        },
        {
            "name": "turn",
            "span_id": "turn-user",
            "start_time_unix_nano": 200,
            "attributes": {"turn.number": 1},
        },
        {
            "name": "llm_response",
            "span_id": "llm-user",
            "parent_span_id": "turn-user",
            "attributes": {"metrics.ttfb": 1.396},
        },
    ]
    turns = derive_turns_from_spans(spans)
    assert len(turns) == 2
    assert turns[0]["turn_number"] == 1
    assert turns[0]["llm_ttfb_ms"] == 1551.0
    assert turns[1]["turn_number"] == 2
    assert turns[1]["llm_ttfb_ms"] == 1396.0


def test_finalize_turn_uses_llm_as_sut_when_user_bot_latency_missing():
    spans = [
        {
            "name": "turn",
            "span_id": "turn-1",
            "attributes": {
                "turn.number": 1,
                "turn.duration_seconds": 7.14,
            },
        },
        {
            "name": "llm_response",
            "span_id": "llm-1",
            "parent_span_id": "turn-1",
            "attributes": {"metrics.ttfb": 1.138},
        },
    ]
    turns = derive_turns_from_spans(spans)
    assert turns[0]["sut_response_latency_ms"] == 1138.0
    assert turns[0]["llm_ttfb_ms"] == 1138.0
    assert turns[0].get("tts_ttfb_ms") is None


def test_derive_turns_llm_response_with_turn_number_on_span():
    spans = [
        {
            "name": "llm_response",
            "span_id": "llm-1",
            "attributes": {
                "turn.number": 1,
                "metrics.ttfb": 1.138,
            },
        },
    ]
    turns = derive_turns_from_spans(spans)
    assert turns[0]["llm_ttfb_ms"] == 1138.0


def test_extract_correlation_ids_validates_call_short_id():
    ids = extract_correlation_ids(
        [{"attributes": {"efficientai.call_short_id": "abc"}}]
    )
    assert ids.get("call_short_id") is None

    ids = extract_correlation_ids(
        [{"attributes": {"efficientai.call_short_id": "482931"}}]
    )
    assert ids["call_short_id"] == "482931"


def test_merge_tier1_and_otel_turns():
    tier1 = [{"turn_number": 1, "sut_response_latency_ms": 900.0}]
    otel = [{"turn_number": 1, "llm_ttfb_ms": 400.0}]
    merged = merge_tier1_and_otel_turns(tier1, otel)
    assert merged[0]["sut_response_latency_ms"] == 900.0
    assert merged[0]["llm_ttfb_ms"] == 400.0


def test_filter_spans_for_trace_keeps_all_trace_ids_when_call_scoped():
    """Multi-agent Pipecat may emit multiple OTLP trace_ids for one call_short_id."""
    spans = [
        {
            "trace_id": "call-a",
            "span_id": "turn-a",
            "name": "turn",
            "start_time_unix_nano": 100,
            "attributes": {"efficientai.call_short_id": "111111"},
        },
        {
            "trace_id": "call-b",
            "span_id": "turn-b",
            "name": "turn",
            "start_time_unix_nano": 200,
            "attributes": {"efficientai.call_short_id": "111111"},
        },
        {
            "trace_id": "call-b",
            "span_id": "llm-b",
            "name": "llm_response",
            "parent_span_id": "turn-b",
            "attributes": {"efficientai.call_short_id": "111111", "metrics.ttfb": 1.0},
        },
    ]
    filtered = filter_spans_for_trace(spans, call_short_id="111111")
    trace_ids = {s.get("trace_id") for s in filtered}
    assert trace_ids == {"call-a", "call-b"}
    turns = derive_turns_from_spans(filtered)
    assert len(turns) == 2


def test_derive_turns_assigns_orphan_components_by_time_window():
    """Orphan STT/TTS from another worker should land in the chronologically correct turn."""
    spans = [
        {
            "name": "turn",
            "span_id": "turn-1",
            "start_time_unix_nano": 100,
            "end_time_unix_nano": 8_000_000_000,
            "attributes": {"turn.user_bot_latency_seconds": 1.5},
        },
        {
            "name": "llm_response",
            "span_id": "llm-1",
            "parent_span_id": "turn-1",
            "start_time_unix_nano": 200,
            "attributes": {"metrics.ttfb": 1.0, "output": "Welcome to Acme Corp!"},
        },
        {
            "name": "turn",
            "span_id": "turn-2",
            "start_time_unix_nano": 10_000_000_000,
            "end_time_unix_nano": 20_000_000_000,
            "attributes": {},
        },
        {
            "name": "tts",
            "span_id": "tts-orphan",
            "start_time_unix_nano": 500,
            "attributes": {
                "gen_ai.operation.name": "tts",
                "metrics.ttfb": 0.2,
                "text": "Welcome to Acme Corp!",
                "turn.number": 1,
            },
        },
        {
            "name": "stt",
            "span_id": "stt-orphan",
            "start_time_unix_nano": 10_500_000_000,
            "attributes": {
                "gen_ai.operation.name": "stt",
                "metrics.ttfb": 0.5,
                "transcript": "rocket boots",
                "turn.number": 1,
            },
        },
    ]
    turns = derive_turns_from_spans(spans)
    assert len(turns) == 2
    assert turns[0]["tts_ttfb_ms"] == 200.0
    assert turns[0]["llm_ttfb_ms"] == 1000.0
    assert "Welcome to Acme Corp" in turns[0]["transcript"]
    assert turns[1]["stt_ttfb_ms"] == 500.0
    assert "rocket boots" in turns[1]["transcript"]


def test_derive_turns_pairs_user_with_async_bot_response():
    spans = [
        {
            "name": "llm_response",
            "span_id": "llm-greet",
            "start_time_unix_nano": 100,
            "attributes": {"metrics.ttfb": 1.6, "output": "Welcome to Acme Corp!"},
        },
        {
            "name": "llm_response",
            "span_id": "llm-support",
            "start_time_unix_nano": 200,
            "attributes": {"metrics.ttfb": 8.9, "output": "Our partners would be happy to help."},
        },
        {
            "name": "tts",
            "span_id": "tts-greet",
            "start_time_unix_nano": 300,
            "attributes": {
                "gen_ai.operation.name": "tts",
                "metrics.ttfb": 0.27,
                "text": "Welcome to Acme Corp!",
            },
        },
        {
            "name": "stt",
            "span_id": "stt-user",
            "start_time_unix_nano": 10_000,
            "attributes": {
                "gen_ai.operation.name": "stt",
                "metrics.ttfb": 0.54,
                "transcript": "Invisible Bank",
            },
        },
        {
            "name": "tts",
            "span_id": "tts-support",
            "start_time_unix_nano": 20_000,
            "attributes": {
                "gen_ai.operation.name": "tts",
                "metrics.ttfb": 0.36,
                "text": "Our partners would be happy to help.",
            },
        },
    ]
    turns = derive_turns_from_spans(spans)
    assert len(turns) == 2
    assert "Welcome" in turns[0]["extra"]["assistant_text"]
    assert turns[0]["tts_ttfb_ms"] == 270.0
    assert "Invisible Bank" in turns[1]["extra"]["user_text"]
    assert "partners" in turns[1]["extra"]["assistant_text"]
    assert turns[1]["tts_ttfb_ms"] == 360.0


def test_derive_turns_extracts_s2s_latency():
    spans = [
        {
            "name": "s2s",
            "span_id": "s2s-1",
            "start_time_unix_nano": 100,
            "attributes": {
                "gen_ai.operation.name": "s2s",
                "gen_ai.request.model": "gpt-4o-realtime-preview",
                "metrics.ttfb": 0.85,
                "transcript": "book a flight",
                "transcript.is_input": True,
                "output": "Sure, where would you like to go?",
            },
        },
    ]
    turns = derive_turns_from_spans(spans)
    assert len(turns) == 1
    assert turns[0]["s2s_ttfb_ms"] == 850.0
    assert turns[0]["extra"]["pipeline_mode"] == "s2s"
    assert "book a flight" in turns[0]["transcript"]


def test_derive_turns_skips_llm_input_json_for_transcript():
    spans = [
        {
            "name": "turn",
            "span_id": "turn-1",
            "start_time_unix_nano": 100,
            "attributes": {"turn.number": 1},
        },
        {
            "name": "llm_response",
            "span_id": "llm-1",
            "parent_span_id": "turn-1",
            "attributes": {
                "metrics.ttfb": 1.0,
                "input": '[{"role": "user", "content": "hello"}]',
                "output": "Hi there!",
            },
        },
    ]
    turns = derive_turns_from_spans(spans)
    assert turns[0]["transcript"] == "Assistant: Hi there!"


def test_extract_pipeline_models_from_spans():
    from app.services.synthetic_traces.otlp_mapper import extract_pipeline_models

    models = extract_pipeline_models(
        [
            {
                "name": "stt",
                "attributes": {
                    "gen_ai.operation.name": "stt",
                    "gen_ai.system": "elevenlabs",
                    "gen_ai.request.model": "scribe_v2_realtime",
                },
            },
            {
                "name": "llm_response",
                "attributes": {
                    "gen_ai.operation.name": "chat",
                    "gen_ai.provider.name": "fireworks",
                    "gen_ai.request.model": "accounts/fireworks/models/deepseek-v4-flash-0731",
                },
            },
            {
                "name": "tts",
                "attributes": {
                    "gen_ai.operation.name": "tts",
                    "gen_ai.provider.name": "elevenlabs",
                    "settings.model": "eleven_flash_v2_5",
                },
            },
        ]
    )
    assert models["stt"]["provider"] == "elevenlabs"
    assert models["stt"]["model"] == "scribe_v2_realtime"
    assert models["llm"]["model"] == "deepseek-v4-flash-0731"
    assert models["tts"]["model"] == "eleven_flash_v2_5"


def test_spans_indicate_session_end():
    from app.services.synthetic_traces.otlp_mapper import spans_indicate_session_end

    assert spans_indicate_session_end(
        [
            {
                "name": "conversation",
                "end_time_unix_nano": 1_000_000_000,
                "attributes": {},
            }
        ]
    )
    assert spans_indicate_session_end(
        [{"name": "turn", "attributes": {"turn.ended_by_conversation_end": True}}]
    )
    assert not spans_indicate_session_end(
        [{"name": "turn", "attributes": {"turn.number": 1}}]
    )
