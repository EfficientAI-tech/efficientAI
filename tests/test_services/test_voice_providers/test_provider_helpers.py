"""Tests for pure helper behavior in provider classes."""

from app.services.voice_providers.elevenlabs import ElevenLabsVoiceProvider
from app.services.voice_providers.vapi import VapiVoiceProvider


def test_strip_code_fences_handles_complete_and_partial_blocks():
    provider = ElevenLabsVoiceProvider(api_key="k")

    full = "```markdown\nHello world\n```"
    partial = "```text\nHello world"
    plain = "Hello world"

    assert provider._strip_code_fences(full) == "Hello world"
    assert provider._strip_code_fences(partial) == "Hello world"
    assert provider._strip_code_fences(plain) == "Hello world"


def test_vapi_make_json_serializable_converts_nested_values():
    provider = VapiVoiceProvider(api_key="k")
    payload = {"outer": [{"num": 1, "flag": True}, {"text": "ok"}]}
    result = provider._make_json_serializable(payload)

    assert result == payload
