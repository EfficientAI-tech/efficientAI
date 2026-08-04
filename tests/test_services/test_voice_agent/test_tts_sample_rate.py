"""Tests for voice bundle TTS sample rate resolution."""

from types import SimpleNamespace

from app.services.voice_agent.tts_sample_rate import (
    DEFAULT_TTS_SAMPLE_RATE_HZ,
    RTVI_WEBSOCKET_TRANSPORT_SAMPLE_RATE_HZ,
    SILERO_VAD_SAMPLE_RATE_HZ,
    resolve_tts_sample_rate_hz,
    resolve_websocket_audio_in_sample_rate_hz,
    resolve_websocket_audio_out_sample_rate_hz,
    resolve_websocket_transport_sample_rate_hz,
    tts_sample_rates_for_provider,
)


def test_default_sample_rate_without_config():
    bundle = SimpleNamespace(tts_config=None)
    assert resolve_tts_sample_rate_hz(bundle, "cartesia") == DEFAULT_TTS_SAMPLE_RATE_HZ


def test_reads_configured_rate():
    bundle = SimpleNamespace(tts_config={"sample_rate_hz": 16000})
    assert resolve_tts_sample_rate_hz(bundle, "cartesia") == 16000


def test_telephony_clamps_to_8k():
    bundle = SimpleNamespace(tts_config={"sample_rate_hz": 16000})
    assert resolve_tts_sample_rate_hz(bundle, "cartesia", telephony_mode=True) == 8000


def test_unsupported_rate_falls_back_for_provider():
    bundle = SimpleNamespace(tts_config={"sample_rate_hz": 22050})
    assert resolve_tts_sample_rate_hz(bundle, "smallest") == 8000


def test_tts_sample_rates_for_provider_intersection():
    rates = tts_sample_rates_for_provider("sarvam")
    assert 8000 in rates
    assert 22050 in rates
    assert 44100 not in rates


def test_openai_has_no_ui_rates():
    assert tts_sample_rates_for_provider("openai") == []


def test_rtvi_transport_stays_24k_while_tts_can_be_8k():
    bundle = SimpleNamespace(tts_config={"sample_rate_hz": 8000})
    assert resolve_tts_sample_rate_hz(bundle, "cartesia") == 8000
    assert resolve_websocket_audio_out_sample_rate_hz(telephony_mode=False) == (
        RTVI_WEBSOCKET_TRANSPORT_SAMPLE_RATE_HZ
    )
    assert resolve_websocket_audio_in_sample_rate_hz(telephony_mode=False) == (
        SILERO_VAD_SAMPLE_RATE_HZ
    )
    assert resolve_websocket_transport_sample_rate_hz(telephony_mode=True) == 8000
    assert resolve_websocket_audio_in_sample_rate_hz(telephony_mode=True) == 8000
