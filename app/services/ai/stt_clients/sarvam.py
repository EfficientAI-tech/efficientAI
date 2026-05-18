"""Sarvam AI batch transcription client.

Sarvam's real-time ``/speech-to-text`` endpoint caps audio at 30
seconds per request. For longer recordings (the common case for call
imports) we split the file into <=28s WAV chunks via ``pydub`` and
concatenate the text. Doing the chunking client-side avoids forcing
operators to switch to Sarvam's batch (job) API for every long file.
"""

from __future__ import annotations

import io
import logging
import os
import tempfile
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

SARVAM_STT_URL = "https://api.sarvam.ai/speech-to-text"

# Sarvam's documented limit is 30s; leave a safety margin so a slightly
# longer chunk from rounding doesn't trip the API.
_CHUNK_SECONDS = 28
_MAX_INLINE_SECONDS = 28  # if shorter than this, send as-is


def _sarvam_post_chunk(
    file_path: str,
    model: str,
    api_key: str,
    language: Optional[str],
) -> Dict[str, Any]:
    """POST a single (<=30s) audio chunk and return the raw JSON dict."""
    headers = {"api-subscription-key": api_key}
    data: Dict[str, Any] = {"model": model}
    if language:
        # Sarvam accepts ``language_code`` like ``hi-IN`` / ``en-IN``;
        # callers usually pass either form. Pass through unchanged.
        data["language_code"] = language

    with open(file_path, "rb") as f:
        files = {
            "file": (
                os.path.basename(file_path) or "audio.wav",
                f,
                "audio/wav",
            ),
        }
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(
                SARVAM_STT_URL,
                headers=headers,
                data=data,
                files=files,
            )
            resp.raise_for_status()
            return resp.json()


def _split_audio_to_chunks(audio_file_path: str, chunk_seconds: int) -> List[str]:
    """Split ``audio_file_path`` into WAV chunks of up to ``chunk_seconds``.

    Returns a list of temp file paths the caller is responsible for
    deleting. We always re-encode to WAV PCM so Sarvam doesn't reject
    the chunk on container/codec edge cases.
    """
    from pydub import AudioSegment

    audio = AudioSegment.from_file(audio_file_path)
    chunk_ms = chunk_seconds * 1000
    paths: List[str] = []
    for start in range(0, len(audio), chunk_ms):
        segment = audio[start : start + chunk_ms]
        tmp = tempfile.NamedTemporaryFile(
            delete=False, suffix=".wav", prefix="sarvam_chunk_"
        )
        tmp.close()
        segment.export(tmp.name, format="wav")
        paths.append(tmp.name)
    return paths


def transcribe_sarvam(
    audio_file_path: str,
    model: str,
    api_key: str,
    language: Optional[str] = None,
) -> Dict[str, Any]:
    """Transcribe an audio file via Sarvam's real-time STT endpoint.

    Files longer than ~28s are split client-side into smaller chunks
    and the resulting transcripts are concatenated.
    """
    chosen_model = (model or "saarika:v2.5").strip() or "saarika:v2.5"

    # Decide whether we need to chunk. Cheaply probe duration with
    # pydub; if pydub can't read the file we fall back to a single
    # request and let Sarvam tell us why.
    duration_seconds: Optional[float] = None
    try:
        from pydub import AudioSegment

        duration_seconds = (
            AudioSegment.from_file(audio_file_path).duration_seconds
        )
    except Exception as e:  # noqa: BLE001 - probing only
        logger.warning(
            "[sarvam] could not probe audio duration (%s); sending as-is",
            e,
        )

    if duration_seconds is None or duration_seconds <= _MAX_INLINE_SECONDS:
        result = _sarvam_post_chunk(audio_file_path, chosen_model, api_key, language)
        text = (result.get("transcript") or "").strip()
        return {
            "text": text,
            "language": result.get("language_code") or language or "en",
            "segments": [],
        }

    chunk_paths = _split_audio_to_chunks(audio_file_path, _CHUNK_SECONDS)
    pieces: List[str] = []
    detected_lang: Optional[str] = None
    try:
        for path in chunk_paths:
            chunk_result = _sarvam_post_chunk(path, chosen_model, api_key, language)
            piece = (chunk_result.get("transcript") or "").strip()
            if piece:
                pieces.append(piece)
            if not detected_lang:
                detected_lang = chunk_result.get("language_code")
    finally:
        for path in chunk_paths:
            try:
                os.unlink(path)
            except OSError:
                pass

    return {
        "text": " ".join(pieces).strip(),
        "language": detected_lang or language or "en",
        "segments": [],
    }
