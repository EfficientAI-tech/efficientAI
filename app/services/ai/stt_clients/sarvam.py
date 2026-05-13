"""Sarvam batch transcription client (REST /speech-to-text endpoint).

The realtime endpoint Sarvam exposes for batch transcription
(``POST https://api.sarvam.ai/speech-to-text``) caps each request at
**30 seconds** of audio and rejects longer files with HTTP 400 +
``"Audio duration exceeds the maximum limit of 30 seconds. Please use
the batch API for longer audio files."``.

Rather than implementing Sarvam's multi-step batch jobs API
(``/speech-to-text/job/...`` — init → upload to Azure SAS → start →
poll status → download results) we transparently chunk audio longer
than the cap into ≤28 s WAV slices, send each slice through the realtime
endpoint, and concatenate the resulting transcripts.  For short clips
the chunked path is skipped entirely, so behaviour is unchanged.

The streaming/WebSocket Sarvam STT path used by live voice agents is
implemented separately in ``src/efficientai/services/sarvam/stt.py`` and
does not have this 30 s limit.
"""

from __future__ import annotations

import logging
import os
import tempfile
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# A 2 s safety margin under Sarvam's 30 s ceiling — empirically reliable
# even when the audio container reports a slightly different duration
# than what the API measures internally.
_SARVAM_MAX_CHUNK_SECONDS = 28.0


def _post_chunk(
    *,
    chunk_path: str,
    model: str,
    api_key: str,
    language: Optional[str],
) -> Dict[str, Any]:
    """POST a single ≤30 s chunk to Sarvam's /speech-to-text endpoint."""
    import httpx

    url = "https://api.sarvam.ai/speech-to-text"
    headers = {"api-subscription-key": api_key}

    with open(chunk_path, "rb") as f:
        audio_bytes = f.read()

    files = {"file": ("audio.wav", audio_bytes, "audio/wav")}
    data: Dict[str, str] = {"model": model or "saarika:v2.5"}
    if language:
        data["language_code"] = language

    resp = httpx.post(url, headers=headers, files=files, data=data, timeout=60.0)
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        body = (e.response.text or "").strip()
        detail = f"{e}"
        if body:
            detail = f"{detail} | response={body[:500]}"
        raise RuntimeError(detail) from e
    return resp.json()


def transcribe_sarvam(
    audio_file_path: str,
    model: str,
    api_key: str,
    language: Optional[str] = None,
) -> Dict[str, Any]:
    """Transcribe an audio file via the Sarvam AI Speech-to-Text REST API.

    Audio longer than ~28 s is sliced into ≤28 s WAV chunks (using
    pydub), each one sent through ``/speech-to-text``, and the resulting
    transcripts concatenated. The chunked path is transparent to
    callers — the return shape matches the single-shot case.
    """
    # Probe duration cheaply with pydub. If anything goes wrong (corrupt
    # audio, missing ffmpeg, etc.) we fall back to a single-shot request
    # and let Sarvam raise its own error — that preserves existing
    # behaviour for callers passing already-short clips.
    duration_seconds: Optional[float] = None
    full_audio = None
    try:
        from pydub import AudioSegment

        full_audio = AudioSegment.from_file(audio_file_path)
        duration_seconds = len(full_audio) / 1000.0
    except Exception as exc:  # noqa: BLE001 — duration probe is best-effort
        logger.warning(
            "transcribe_sarvam: could not measure duration for %s (%s); "
            "sending in one shot",
            audio_file_path,
            exc,
        )

    # Short-clip fast path — keeps behaviour identical for ≤30 s recordings.
    if (
        duration_seconds is None
        or duration_seconds <= _SARVAM_MAX_CHUNK_SECONDS
    ):
        result = _post_chunk(
            chunk_path=audio_file_path,
            model=model,
            api_key=api_key,
            language=language,
        )
        return {
            "text": result.get("transcript", ""),
            "language": result.get("language_code", language or "unknown"),
            "segments": [],
        }

    # Long-clip path — slice into ≤28 s WAV chunks and stitch together.
    chunk_ms = int(_SARVAM_MAX_CHUNK_SECONDS * 1000)
    transcripts: List[str] = []
    detected_language: Optional[str] = None

    chunk_paths: List[str] = []
    try:
        for start_ms in range(0, len(full_audio), chunk_ms):  # type: ignore[arg-type]
            chunk = full_audio[start_ms : start_ms + chunk_ms]  # type: ignore[index]
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
                chunk_path = tmp.name
            chunk.export(chunk_path, format="wav")
            chunk_paths.append(chunk_path)

            chunk_result = _post_chunk(
                chunk_path=chunk_path,
                model=model,
                api_key=api_key,
                language=language,
            )
            piece = (chunk_result.get("transcript") or "").strip()
            if piece:
                transcripts.append(piece)
            if not detected_language:
                detected_language = chunk_result.get("language_code") or None
    finally:
        for path in chunk_paths:
            try:
                os.remove(path)
            except OSError:
                pass

    return {
        "text": " ".join(transcripts).strip(),
        "language": detected_language or language or "unknown",
        "segments": [],
    }
