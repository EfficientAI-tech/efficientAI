"""Smallest Pulse batch transcription client (REST /pulse/get_text)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def transcribe_smallest(
    audio_file_path: str,
    model: str,
    api_key: str,
    language: Optional[str] = None,
) -> Dict[str, Any]:
    """Transcribe an audio file via Smallest Pulse (pre-recorded) REST API."""
    import httpx

    # The ``model`` argument is intentionally unused — Smallest's
    # pre-recorded endpoint selects the model from the API key's plan
    # rather than from a request field. We keep the parameter for
    # signature symmetry with the other ``transcribe_<provider>`` callables.
    _ = model

    url = "https://api.smallest.ai/waves/v1/pulse/get_text"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/octet-stream",
    }
    params: Dict[str, str] = {
        "word_timestamps": "true",
        "sentence_timestamps": "true",
        "language": language or "multi",
    }

    with open(audio_file_path, "rb") as f:
        audio_bytes = f.read()

    response = httpx.post(
        url,
        headers=headers,
        params=params,
        content=audio_bytes,
        timeout=120.0,
    )
    response.raise_for_status()
    result = response.json()

    words = []
    for w in result.get("words", []) or []:
        if not isinstance(w, dict):
            continue
        words.append(
            {
                "word": w.get("word", "") or "",
                "start": float(w.get("start", 0) or 0),
                "end": float(w.get("end", 0) or 0),
                "speaker": w.get("speaker"),
            }
        )

    segments = []
    for utterance in result.get("utterances", []) or []:
        if not isinstance(utterance, dict):
            continue
        segments.append(
            {
                "start": float(utterance.get("start", 0) or 0),
                "end": float(utterance.get("end", 0) or 0),
                "text": utterance.get("text", "") or "",
                "speaker": utterance.get("speaker"),
            }
        )

    text = (result.get("transcription") or "").strip()
    if not segments and text:
        segments = [{"start": 0.0, "end": float(result.get("audio_length", 0) or 0), "text": text}]

    return {
        "text": text,
        "language": result.get("language", language or "en"),
        "segments": segments,
        "words": words,
    }
