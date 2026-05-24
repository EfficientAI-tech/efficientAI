"""ElevenLabs batch transcription client (Speech-to-Text REST API)."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

ELEVENLABS_STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"


def transcribe_elevenlabs(
    audio_file_path: str,
    model: str,
    api_key: str,
    language: Optional[str] = None,
) -> Dict[str, Any]:
    """Transcribe an audio file via the ElevenLabs STT REST API.

    Uses the multipart-form ``/v1/speech-to-text`` endpoint so we don't
    take a hard dependency on a specific ElevenLabs SDK version.
    """
    chosen_model = (model or "scribe_v1").strip() or "scribe_v1"

    headers = {"xi-api-key": api_key}
    data: Dict[str, Any] = {"model_id": chosen_model}
    if language:
        # ElevenLabs accepts ISO-639-1 codes ("en", "hi", ...); accept
        # whatever the caller passes — no normalization here.
        data["language_code"] = language

    with open(audio_file_path, "rb") as f:
        files = {
            "file": (
                os.path.basename(audio_file_path) or "audio",
                f,
                "application/octet-stream",
            ),
        }
        with httpx.Client(timeout=180.0) as client:
            resp = client.post(
                ELEVENLABS_STT_URL,
                headers=headers,
                data=data,
                files=files,
            )
            resp.raise_for_status()
            payload = resp.json()

    text = (payload.get("text") or "").strip()
    return {
        "text": text,
        "language": payload.get("language_code") or language or "en",
        "segments": [],
    }
