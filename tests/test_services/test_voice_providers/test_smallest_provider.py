"""Tests for Smallest voice provider adapter."""

import pytest

from app.services.voice_providers.smallest import SmallestVoiceProvider


def test_create_web_call_requires_phone_number():
    provider = SmallestVoiceProvider(api_key="key")

    with pytest.raises(ValueError, match="outbound call creation only"):
        provider.create_web_call(agent_id="agent-1")


def test_retrieve_call_metrics_normalizes_transcript_segments(monkeypatch):
    provider = SmallestVoiceProvider(api_key="key")
    payload = {
        "conversationId": "conv-1",
        "status": "completed",
        "duration": 8.2,
        "startedAt": "2026-04-13T10:00:00Z",
        "recordingUrl": "https://audio.example/call.wav",
        "transcript": [
            {"role": "user", "text": "hello", "timeInCallSecs": 0.5},
            {"role": "agent", "text": "hi there", "timeInCallSecs": 1.3},
        ],
    }
    monkeypatch.setattr(provider, "_get_conversation", lambda _call_id: payload)

    metrics = provider.retrieve_call_metrics("conv-1")

    assert metrics["call_id"] == "conv-1"
    assert metrics["call_status"] == "ended"
    assert metrics["duration_seconds"] == 8.2
    assert metrics["recording_url"] == "https://audio.example/call.wav"
    assert metrics["transcript"].startswith("User: hello")
    assert len(metrics["transcript_object"]) == 2


def test_extract_agent_prompt_prefers_global_prompt(monkeypatch):
    provider = SmallestVoiceProvider(api_key="key")
    monkeypatch.setattr(
        provider,
        "get_agent",
        lambda _agent_id: {"globalPrompt": "System instructions", "prompt": "fallback"},
    )

    assert provider.extract_agent_prompt("agent-1") == "System instructions"
