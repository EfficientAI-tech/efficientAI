"""Lightweight Deepgram TTS helper for app-level synthesis."""

import time
from typing import Any, Dict, Optional, Tuple

import requests


def synthesize_deepgram_bytes(
    text: str,
    model: str,
    api_key: str,
    voice: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[bytes, float]:
    """Synthesize speech via Deepgram and return (audio_bytes, ttfb_ms)."""
    voice_model = voice or "aura-asteria-en"
    url = f"https://api.deepgram.com/v1/speak?model={voice_model}"

    effective_config = dict(config) if config else {}
    sample_rate_hz = effective_config.pop("sample_rate_hz", None)
    if sample_rate_hz:
        url += f"&sample_rate={int(sample_rate_hz)}"

    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/json",
    }
    body = {"text": text}

    start = time.time()
    resp = requests.post(url, json=body, headers=headers, stream=True, timeout=60)
    if resp.status_code != 200:
        error_text = b"".join(resp.iter_content(chunk_size=None)).decode(errors="replace")[:500]
        raise RuntimeError(f"Deepgram TTS failed ({resp.status_code}): {error_text}")

    ttfb_ms: Optional[float] = None
    chunks: list[bytes] = []
    for chunk in resp.iter_content(chunk_size=8192):
        if chunk:
            if ttfb_ms is None:
                ttfb_ms = (time.time() - start) * 1000
            chunks.append(chunk)

    return b"".join(chunks), ttfb_ms if ttfb_ms is not None else (time.time() - start) * 1000

