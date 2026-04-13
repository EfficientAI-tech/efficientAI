"""Lightweight Smallest Lightning v3.1 TTS helper for app-level synthesis."""

import time
from typing import Any, Dict, Optional, Tuple

import requests


def synthesize_smallest_bytes(
    text: str,
    model: str,
    api_key: str,
    voice: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[bytes, float]:
    """Synthesize speech via Smallest and return (audio_bytes, ttfb_ms)."""
    effective_config = dict(config) if config else {}

    voice_id = voice or effective_config.pop("voice_id", "daniel")
    sample_rate_hz = int(effective_config.pop("sample_rate_hz", effective_config.pop("sample_rate", 24000)))
    speed = float(effective_config.pop("speed", 1.0))
    language = effective_config.pop("language", "en")
    output_format = effective_config.pop("output_format", "wav")

    endpoint_model = model or "lightning-v3.1"
    if endpoint_model != "lightning-v3.1":
        endpoint_model = "lightning-v3.1"

    payload: Dict[str, Any] = {
        "text": text,
        "voice_id": voice_id,
        "sample_rate": sample_rate_hz,
        "speed": speed,
        "language": language,
        "output_format": output_format,
    }
    if effective_config:
        payload.update(effective_config)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "audio/wav",
        "Content-Type": "application/json",
    }
    url = f"https://api.smallest.ai/waves/v1/{endpoint_model}/get_speech"

    start = time.time()
    response = requests.post(url, json=payload, headers=headers, timeout=90)
    if response.status_code != 200:
        error_text = response.text[:500] if response.text else ""
        raise RuntimeError(f"Smallest TTS failed ({response.status_code}): {error_text}")
    ttfb_ms = (time.time() - start) * 1000

    return response.content, ttfb_ms
