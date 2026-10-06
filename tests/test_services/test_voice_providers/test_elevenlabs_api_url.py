"""Tests for ElevenLabs API base URL normalization."""

import pytest

from app.services.voice_providers.elevenlabs import ElevenLabsVoiceProvider
from app.services.voice_providers.elevenlabs_api_url import (
    ELEVENLABS_GLOBAL_ORIGIN,
    elevenlabs_api_v1_base,
    elevenlabs_realtime_stt_host,
    elevenlabs_speech_to_text_url,
    normalize_elevenlabs_api_base_url,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("https://api.elevenlabs.io", None),
        ("https://api.elevenlabs.io/v1", None),
        (
            "https://api.eu.residency.elevenlabs.io",
            "https://api.eu.residency.elevenlabs.io",
        ),
        (
            "https://api.in.residency.elevenlabs.io/v1",
            "https://api.in.residency.elevenlabs.io",
        ),
        (
            "api.eu.residency.elevenlabs.io",
            "https://api.eu.residency.elevenlabs.io",
        ),
    ],
)
def test_normalize_elevenlabs_api_base_url_valid(raw, expected):
    assert normalize_elevenlabs_api_base_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "http://api.elevenlabs.io",
        "https://evil.example.com",
        "https://api.elevenlabs.io/v1/convai/agents",
    ],
)
def test_normalize_elevenlabs_api_base_url_rejects_invalid(raw):
    with pytest.raises(ValueError):
        normalize_elevenlabs_api_base_url(raw)


def test_elevenlabs_voice_provider_uses_residency_base():
    provider = ElevenLabsVoiceProvider(
        api_key="k",
        base_url="https://api.eu.residency.elevenlabs.io",
    )
    assert provider.api_url == "https://api.eu.residency.elevenlabs.io/v1"


def test_elevenlabs_api_v1_base_defaults_to_global():
    assert elevenlabs_api_v1_base(None) == f"{ELEVENLABS_GLOBAL_ORIGIN}/v1"


def test_elevenlabs_stt_and_realtime_urls_use_residency():
    eu = "https://api.eu.residency.elevenlabs.io"
    assert elevenlabs_speech_to_text_url(eu) == f"{eu}/v1/speech-to-text"
    assert elevenlabs_realtime_stt_host(eu) == "api.eu.residency.elevenlabs.io"
