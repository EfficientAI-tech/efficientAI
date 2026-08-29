"""Tests for incremental live observability ingest merge helpers."""

from app.services.observability.live_ingest import merge_live_event_call_data


def test_merge_call_ended_persists_recording_url():
    merged = merge_live_event_call_data(
        existing_call_data={"live_transcript": [{"role": "user", "content": "hi"}]},
        event={
            "event_type": "call.ended",
            "event_ts": "2026-08-18T09:00:00Z",
            "seq": 3,
            "platform": "pipecat",
            "payload": {
                "endedAt": "2026-08-18T09:00:05Z",
                "recording_url": "https://cdn.example/rec.wav",
                "duration_seconds": 5.2,
            },
        },
        max_out_of_order_seq=5,
    )
    assert merged["recording_url"] == "https://cdn.example/rec.wav"
    assert merged["duration_seconds"] == 5.2
    assert merged["status"] == "ended"


def test_merge_turn_events_build_live_transcript():
    merged = merge_live_event_call_data(
        existing_call_data={},
        event={
            "event_type": "turn.assistant",
            "event_ts": "2026-08-18T09:00:01Z",
            "seq": 2,
            "platform": "livekit",
            "payload": {"content": "Hello there", "latency": {"llm_ms": 400}},
        },
        max_out_of_order_seq=5,
    )
    assert len(merged["live_transcript"]) == 1
    assert merged["live_transcript"][0]["content"] == "Hello there"
    assert merged["messages"][0]["role"] == "assistant"
