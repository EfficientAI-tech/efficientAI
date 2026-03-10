"""Lightweight Sarvam TTS helper for app-level synthesis."""

import base64
import time
from typing import Any, Dict, Optional, Tuple

import requests


def synthesize_sarvam_bytes(
    text: str,
    model: str,
    api_key: str,
    voice: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[bytes, float]:
    """Synthesize speech via Sarvam and return (audio_bytes, ttfb_ms)."""
    effective_config = dict(config) if config else {}
    # Support legacy field naming used by Voice Playground.
    sample_rate_hz = effective_config.pop("sample_rate_hz", None)

    payload: Dict[str, Any] = {
        "text": text,
        "target_language_code": effective_config.pop("target_language_code", "en-IN"),
        "speaker": voice or effective_config.pop("speaker", "anushka"),
        "model": model,
        "sample_rate": int(sample_rate_hz) if sample_rate_hz else int(effective_config.pop("sample_rate", 22050)),
        "enable_preprocessing": bool(effective_config.pop("enable_preprocessing", False)),
    }

    # Optional voice controls.
    for key in ("pitch", "pace", "loudness", "temperature"):
        if key in effective_config:
            payload[key] = effective_config.pop(key)

    # Allow explicit overrides as a last step.
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

