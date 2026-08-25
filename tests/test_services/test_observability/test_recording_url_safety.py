"""Tests for observability recording URL SSRF guards."""

import socket
from unittest.mock import patch

import pytest

from app.services.observability.recording_url_safety import (
    assert_elevenlabs_recording_url,
    build_elevenlabs_conversation_audio_url,
)
from app.services.telephony.exotel_client import ExotelInvalidContentError


@pytest.fixture(autouse=True)
def _mock_public_dns():
    with patch.object(
        socket,
        "getaddrinfo",
        return_value=[(None, None, None, None, ("52.0.0.1", 0))],
    ):
        yield


def test_build_elevenlabs_conversation_audio_url():
    url = build_elevenlabs_conversation_audio_url("conv_9001k1zph3fkeh5s8xg9z90swaqa")
    assert url == (
        "https://api.elevenlabs.io/v1/convai/conversations/"
        "conv_9001k1zph3fkeh5s8xg9z90swaqa/audio"
    )


def test_build_elevenlabs_conversation_audio_url_rejects_path_injection():
    with pytest.raises(ExotelInvalidContentError, match="unexpected characters"):
        build_elevenlabs_conversation_audio_url("conv_abc/../evil")


def test_assert_elevenlabs_recording_url_allows_provider_endpoint():
    assert_elevenlabs_recording_url(
        "https://api.elevenlabs.io/v1/convai/conversations/conv_123/audio"
    )


def test_assert_elevenlabs_recording_url_rejects_non_elevenlabs_host():
    with pytest.raises(ExotelInvalidContentError, match="not allowlisted"):
        assert_elevenlabs_recording_url("https://evil.example/recording.mp3")


def test_assert_elevenlabs_recording_url_rejects_non_audio_path():
    with pytest.raises(ExotelInvalidContentError, match="not an allowed conversation audio endpoint"):
        assert_elevenlabs_recording_url("https://api.elevenlabs.io/v1/convai/agents/agent_123")
