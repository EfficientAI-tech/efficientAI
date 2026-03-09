"""Lightweight ElevenLabs TTS helper for app-level synthesis."""

import struct
import time
from typing import Any, Dict, Optional, Tuple

import requests
from loguru import logger


ELEVENLABS_HZ_TO_OUTPUT_FORMAT = {
    8000: "pcm_8000",
    16000: "pcm_16000",
    22050: "mp3_22050_32",
    24000: "pcm_24000",
    44100: "mp3_44100_128",
}


def _pcm_to_wav(pcm_bytes: bytes, sample_rate: int, sample_width: int = 2, channels: int = 1) -> bytes:
    """Wrap headerless PCM bytes in a valid WAV container."""
    data_size = len(pcm_bytes)
    byte_rate = sample_rate * channels * sample_width
    block_align = channels * sample_width
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        channels,
        sample_rate,
        byte_rate,
        block_align,
        sample_width * 8,
        b"data",
        data_size,
    )
    return header + pcm_bytes


def synthesize_elevenlabs_bytes(
    text: str,
    model: str,
    api_key: str,
    voice: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[bytes, float]:
    """Synthesize speech via ElevenLabs and return (audio_bytes, ttfb_ms)."""
    voice_id = voice or "21m00Tcm4TlvDq8ikWAM"  # Rachel default
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"

    query_params: Dict[str, str] = {}
    effective_config = dict(config) if config else {}

    sample_rate_hz = effective_config.pop("sample_rate_hz", None)
    output_fmt = None
    if sample_rate_hz:
        hz_int = int(sample_rate_hz)
        output_fmt = ELEVENLABS_HZ_TO_OUTPUT_FORMAT.get(hz_int)
        if output_fmt:
            query_params["output_format"] = output_fmt
        logger.info(f"[ElevenLabs TTS] sample_rate_hz={hz_int} -> output_format={output_fmt}")

    is_pcm = output_fmt and output_fmt.startswith(("pcm_", "ulaw_"))
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/octet-stream" if is_pcm else "audio/mpeg",
    }
    body: Dict[str, Any] = {
        "text": text,
        "model_id": model,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }
    if effective_config:
        body.update(effective_config)

    start = time.time()
    resp = requests.post(url, json=body, headers=headers, params=query_params, stream=True, timeout=60)
    if resp.status_code != 200:
        error_text = b"".join(resp.iter_content(chunk_size=None)).decode(errors="replace")[:500]
        raise RuntimeError(f"ElevenLabs TTS failed ({resp.status_code}): {error_text}")

    ttfb_ms: Optional[float] = None
    chunks: list[bytes] = []
    for chunk in resp.iter_content(chunk_size=8192):
        if chunk:
            if ttfb_ms is None:
                ttfb_ms = (time.time() - start) * 1000
            chunks.append(chunk)

    audio_bytes = b"".join(chunks)
    if is_pcm and sample_rate_hz:
        audio_bytes = _pcm_to_wav(audio_bytes, int(sample_rate_hz))

    return audio_bytes, ttfb_ms if ttfb_ms is not None else (time.time() - start) * 1000

