"""ElevenLabs batch transcription client (REST /v1/speech-to-text)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def transcribe_elevenlabs(
    audio_file_path: str,
    model: str,
    api_key: str,
    language: Optional[str] = None,
) -> Dict[str, Any]:
    """Transcribe an audio file via the ElevenLabs Speech-to-Text REST API.

    Uses ``httpx`` for a synchronous POST (no ElevenLabs SDK in the project).
    The endpoint, headers, and form-field names are identical to those used by
    ``src/efficientai/services/elevenlabs/stt.py`` (async streaming variant).
    """
    import httpx

    url = "https://api.elevenlabs.io/v1/speech-to-text"
    headers = {"xi-api-key": api_key}

    with open(audio_file_path, "rb") as f:
        audio_bytes = f.read()

    files = {"file": ("audio.wav", audio_bytes, "audio/wav")}
    data: Dict[str, str] = {"model_id": model or "scribe_v2"}
    if language:
        data["language_code"] = language

    resp = httpx.post(url, headers=headers, files=files, data=data, timeout=60.0)
    resp.raise_for_status()
    result = resp.json()

    return {
        "text": result.get("text", ""),
        "language": result.get("language_code", language or "en"),
        "segments": [],
    }
