"""Lightweight OpenAI TTS helper for app-level synthesis."""

import time
from typing import Any, Dict, Optional, Tuple


def synthesize_openai_bytes(
    text: str,
    model: str,
    api_key: str,
    voice: Optional[str] = "alloy",
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[bytes, float]:
    """Synthesize speech via OpenAI and return (audio_bytes, ttfb_ms)."""
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        request_params: Dict[str, Any] = {"model": model, "input": text, "voice": voice or "alloy"}
        if config:
            request_params.update(config)

        start = time.time()
        with client.audio.speech.with_streaming_response.create(**request_params) as response:
            ttfb_ms: Optional[float] = None
            chunks: list[bytes] = []
            for chunk in response.iter_bytes():
                if ttfb_ms is None:
                    ttfb_ms = (time.time() - start) * 1000
                chunks.append(chunk)
        return b"".join(chunks), ttfb_ms if ttfb_ms is not None else (time.time() - start) * 1000
    except ImportError:
        raise RuntimeError("OpenAI library not installed. Install with: pip install openai")
    except Exception as e:
        raise RuntimeError(f"OpenAI TTS synthesis failed: {e}")

