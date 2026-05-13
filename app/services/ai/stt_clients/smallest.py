"""Smallest.ai batch transcription client.

Smallest's hosted STT exposes a multipart-form endpoint at
``/v1/speech-to-text``. This client posts the audio file and returns
the transcript text in our common ``{text, language, segments}`` shape.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

SMALLEST_STT_URL = "https://waves-api.smallest.ai/api/v1/speech-to-text"


def transcribe_smallest(
    audio_file_path: str,
    model: str,
    api_key: str,
    language: Optional[str] = None,
) -> Dict[str, Any]:
    """Transcribe an audio file via Smallest.ai's STT REST API."""
    chosen_model = (model or "lightning-large-v1").strip() or "lightning-large-v1"

    headers = {"Authorization": f"Bearer {api_key}"}
    data: Dict[str, Any] = {"model": chosen_model}
    if language:
        data["language"] = language

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
                SMALLEST_STT_URL,
                headers=headers,
                data=data,
                files=files,
            )
            resp.raise_for_status()
            payload = resp.json()

    # Smallest returns either ``transcript`` or ``text`` depending on
    # the route; accept both.
    text = (payload.get("transcript") or payload.get("text") or "").strip()
    return {
        "text": text,
        "language": payload.get("language") or language or "en",
        "segments": [],
    }
