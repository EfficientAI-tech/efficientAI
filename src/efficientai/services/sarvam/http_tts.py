"""Lightweight Sarvam TTS helper for app-level synthesis."""

from __future__ import annotations

import base64
import time
from typing import Any, Dict, Iterable, Iterator, Optional, Tuple

import requests

BULBUL_V4_FLASH = "bulbul:v4-flash"
DEFAULT_V4_SPEAKER = "shubh_enhi_ads"
_V4_STREAM_SAMPLE_RATES = (8000, 16000, 22050, 24000)


def _resolve_speech_sample_rate(effective_config: Dict[str, Any], sample_rate_hz: Any) -> int:
    raw = (
        sample_rate_hz
        or effective_config.pop("speech_sample_rate", None)
        or effective_config.pop("sample_rate", None)
    )
    rate = int(raw) if raw is not None else 24000
    if rate not in _V4_STREAM_SAMPLE_RATES:
        return min(_V4_STREAM_SAMPLE_RATES, key=lambda r: abs(r - rate))
    return rate


def _coerce_audio_chunks(response: Any) -> Iterator[bytes]:
    if response is None:
        return iter(())
    if isinstance(response, (bytes, bytearray)):
        return iter((bytes(response),))
    if isinstance(response, Iterable) and not isinstance(response, (str, dict)):
        return (bytes(chunk) for chunk in response if chunk)
    return iter(())


def _synthesize_sarvam_v4_flash_stream(
    text: str,
    model: str,
    api_key: str,
    voice: Optional[str],
    effective_config: Dict[str, Any],
    sample_rate_hz: Any,
) -> Tuple[bytes, float]:
    try:
        from sarvamai import SarvamAI
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "sarvamai SDK is required for bulbul:v4-flash synthesis but is not installed."
        ) from exc

    language_code = (
        effective_config.pop("target_language_code", None)
        or effective_config.pop("language_code", None)
        or "en-IN"
    )
    speaker = voice or effective_config.pop("speaker", None) or DEFAULT_V4_SPEAKER
    speech_sample_rate = _resolve_speech_sample_rate(effective_config, sample_rate_hz)

    stream_kwargs: Dict[str, Any] = {
        "text": text,
        "language_code": language_code,
        "model": model,
        "speaker": speaker,
        "speech_sample_rate": speech_sample_rate,
        "output_audio_codec": "wav",
        "pace": float(effective_config.pop("pace", 1)),
    }
    if "enable_preprocessing" in effective_config:
        stream_kwargs["enable_preprocessing"] = bool(
            effective_config.pop("enable_preprocessing")
        )
    for key in ("pitch", "loudness"):
        if key in effective_config:
            stream_kwargs[key] = effective_config.pop(key)
    if effective_config:
        stream_kwargs.update(effective_config)

    client = SarvamAI(api_subscription_key=api_key)
    start = time.time()
    response = client.text_to_speech.convert_stream(**stream_kwargs)

    chunks: list[bytes] = []
    ttfb_ms: Optional[float] = None
    for chunk in _coerce_audio_chunks(response):
        if ttfb_ms is None:
            ttfb_ms = (time.time() - start) * 1000
        chunks.append(chunk)

    if not chunks:
        raise RuntimeError("Sarvam TTS convert_stream returned no audio data")

    return b"".join(chunks), ttfb_ms if ttfb_ms is not None else (time.time() - start) * 1000


def _synthesize_sarvam_rest(
    text: str,
    model: str,
    api_key: str,
    voice: Optional[str],
    effective_config: Dict[str, Any],
    sample_rate_hz: Any,
) -> Tuple[bytes, float]:
    payload: Dict[str, Any] = {
        "text": text,
        "target_language_code": effective_config.pop("target_language_code", "en-IN"),
        "speaker": voice or effective_config.pop("speaker", "anushka"),
        "model": model,
        "sample_rate": int(sample_rate_hz)
        if sample_rate_hz
        else int(effective_config.pop("sample_rate", 22050)),
        "enable_preprocessing": bool(effective_config.pop("enable_preprocessing", False)),
    }

    for key in ("pitch", "pace", "loudness", "temperature"):
        if key in effective_config:
            payload[key] = effective_config.pop(key)

    if effective_config:
        payload.update(effective_config)

    headers = {
        "api-subscription-key": api_key,
        "Content-Type": "application/json",
    }
    url = "https://api.sarvam.ai/text-to-speech"

    start = time.time()
    response = requests.post(url, json=payload, headers=headers, timeout=60)
    if response.status_code != 200:
        error_text = response.text[:500] if response.text else ""
        raise RuntimeError(f"Sarvam TTS failed ({response.status_code}): {error_text}")
    ttfb_ms = (time.time() - start) * 1000

    data = response.json()
    audios = data.get("audios") or []
    if not audios:
        raise RuntimeError("Sarvam TTS returned no audio data")

    audio_data = base64.b64decode(audios[0])
    return audio_data, ttfb_ms


def synthesize_sarvam_bytes(
    text: str,
    model: str,
    api_key: str,
    voice: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[bytes, float]:
    """Synthesize speech via Sarvam and return (audio_bytes, ttfb_ms)."""
    effective_config = dict(config) if config else {}
    sample_rate_hz = effective_config.pop("sample_rate_hz", None)
    chosen_model = (model or "bulbul:v3").strip()

    if chosen_model == BULBUL_V4_FLASH or chosen_model.startswith("bulbul:v4"):
        return _synthesize_sarvam_v4_flash_stream(
            text=text,
            model=chosen_model,
            api_key=api_key,
            voice=voice,
            effective_config=effective_config,
            sample_rate_hz=sample_rate_hz,
        )

    return _synthesize_sarvam_rest(
        text=text,
        model=chosen_model,
        api_key=api_key,
        voice=voice,
        effective_config=effective_config,
        sample_rate_hz=sample_rate_hz,
    )