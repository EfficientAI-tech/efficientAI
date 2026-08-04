"""Resolve TTS output sample rate for voice bundles and live pipelines."""

from __future__ import annotations

from typing import Any, List, Optional

from loguru import logger

from app.services.ai.tts_service import PROVIDER_SUPPORTED_SAMPLE_RATES

DEFAULT_TTS_SAMPLE_RATE_HZ = 8000
RTVI_WEBSOCKET_TRANSPORT_SAMPLE_RATE_HZ = 24000
SILERO_VAD_SAMPLE_RATE_HZ = 16000
VOICE_BUNDLE_TTS_RATE_OPTIONS = [8000, 16000, 22050]
ALLOWED_TTS_CONFIG_SAMPLE_RATES = set(VOICE_BUNDLE_TTS_RATE_OPTIONS)


def tts_sample_rates_for_provider(provider: str) -> List[int]:
    """Rates exposed in the voice bundle UI for a TTS provider."""
    key = (provider or "").strip().lower()
    supported = PROVIDER_SUPPORTED_SAMPLE_RATES.get(key, [])
    if not supported:
        return []
    return [hz for hz in VOICE_BUNDLE_TTS_RATE_OPTIONS if hz in supported]


def provider_accepts_sample_rate_kwarg(provider: str) -> bool:
    key = (provider or "").strip().lower()
    return bool(PROVIDER_SUPPORTED_SAMPLE_RATES.get(key))


def _tts_config_dict(voice_bundle: Any) -> dict:
    if voice_bundle is None:
        return {}
    raw = getattr(voice_bundle, "tts_config", None)
    return raw if isinstance(raw, dict) else {}


def resolve_websocket_audio_in_sample_rate_hz(*, telephony_mode: bool = False) -> int:
    """Input transport rate (Silero VAD supports 8 kHz / 16 kHz only)."""
    if telephony_mode:
        return 8000
    return SILERO_VAD_SAMPLE_RATE_HZ


def resolve_websocket_audio_out_sample_rate_hz(*, telephony_mode: bool = False) -> int:
    """Output transport rate (Pipecat RTVI browser client expects 24 kHz)."""
    if telephony_mode:
        return 8000
    return RTVI_WEBSOCKET_TRANSPORT_SAMPLE_RATE_HZ


def resolve_websocket_transport_sample_rate_hz(*, telephony_mode: bool = False) -> int:
    """Legacy alias for output wire rate."""
    return resolve_websocket_audio_out_sample_rate_hz(telephony_mode=telephony_mode)


def resolve_tts_sample_rate_hz(
    voice_bundle: Any,
    provider: str,
    *,
    telephony_mode: bool = False,
) -> int:
    """
    Effective pipeline/TTS sample rate in Hz.

    Telephony (Vobiz) is always clamped to 8 kHz on the wire.
    """
    if telephony_mode:
        return 8000

    key = (provider or "").strip().lower()
    config = _tts_config_dict(voice_bundle)
    requested = config.get("sample_rate_hz")
    if requested is None:
        requested_hz = DEFAULT_TTS_SAMPLE_RATE_HZ
    else:
        try:
            requested_hz = int(requested)
        except (TypeError, ValueError):
            logger.warning("Invalid tts_config.sample_rate_hz={!r}, using default", requested)
            requested_hz = DEFAULT_TTS_SAMPLE_RATE_HZ

    supported = PROVIDER_SUPPORTED_SAMPLE_RATES.get(key, [])
    if not supported:
        return requested_hz

    if requested_hz in supported:
        return requested_hz

    fallback = next((hz for hz in VOICE_BUNDLE_TTS_RATE_OPTIONS if hz in supported), supported[0])
    logger.warning(
        "TTS sample rate {} Hz not supported for provider '{}'; using {} Hz",
        requested_hz,
        key,
        fallback,
    )
    return fallback
