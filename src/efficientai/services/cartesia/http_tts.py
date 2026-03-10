"""Lightweight Cartesia TTS helper for app-level synthesis."""

import time
from typing import Any, Dict, Optional, Tuple

import requests


def synthesize_cartesia_bytes(
    text: str,
    model: str,
    api_key: str,
    voice: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[bytes, float]:
    """Synthesize speech via Cartesia and return (audio_bytes, ttfb_ms)."""
    voice_id = voice or "a0e99841-438c-4a64-b679-ae501e7d6091"
    url = "https://api.cartesia.ai/tts/bytes"
    headers = {
        "X-API-Key": api_key,
        "Cartesia-Version": "2024-06-10",
        "Content-Type": "application/json",
    }

    effective_config = dict(config) if config else {}
    sample_rate_hz = effective_config.pop("sample_rate_hz", None)
    body: Dict[str, Any] = {
        "model_id": model,
        "transcript": text,
        "voice": {"mode": "id", "id": voice_id},
        "output_format": {
            "container": "mp3",
            "bit_rate": 128000,
            "sample_rate": int(sample_rate_hz) if sample_rate_hz else 44100,
        },
    }
    if effective_config:
        body.update(effective_config)

    start = time.time()
    resp = requests.post(url, json=body, headers=headers, stream=True, timeout=60)
    if resp.status_code != 200:
        error_text = b"".join(resp.iter_content(chunk_size=None)).decode(errors="replace")[:500]
        raise RuntimeError(f"Cartesia TTS failed ({resp.status_code}): {error_text}")

    ttfb_ms: Optional[float] = None
    chunks: list[bytes] = []
    for chunk in resp.iter_content(chunk_size=8192):
        if chunk:
            if ttfb_ms is None:
                ttfb_ms = (time.time() - start) * 1000
            chunks.append(chunk)

    return b"".join(chunks), ttfb_ms if ttfb_ms is not None else (time.time() - start) * 1000

