"""OpenAI batch transcription client (Audio → Text REST API).

Handles the response-format quirks across OpenAI's three hosted STT
models from ``app/config/models.json``:

* ``whisper-1`` — supports ``verbose_json`` and
  ``timestamp_granularities``, so we can return per-segment timestamps.
* ``gpt-4o-transcribe`` / ``gpt-4o-mini-transcribe`` — only support
  plain ``json`` (no ``verbose_json``, no timestamp granularities), so
  we get back just the transcript text.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _supports_verbose_json(model: str) -> bool:
    """Only whisper-1 supports verbose_json + timestamp_granularities."""
    return (model or "").strip().lower() == "whisper-1"


def transcribe_openai(
    audio_file_path: str,
    model: str,
    api_key: str,
    language: Optional[str] = None,
) -> Dict[str, Any]:
    """Transcribe an audio file via OpenAI's hosted STT models."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    chosen_model = (model or "whisper-1").strip() or "whisper-1"

    with open(audio_file_path, "rb") as f:
        if _supports_verbose_json(chosen_model):
            response = client.audio.transcriptions.create(
                model=chosen_model,
                file=f,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
                language=language or None,
            )
        else:
            response = client.audio.transcriptions.create(
                model=chosen_model,
                file=f,
                response_format="json",
                language=language or None,
            )

    text = getattr(response, "text", "") or ""
    detected_language = getattr(response, "language", None) or language or "en"

    segments_out: list[Dict[str, Any]] = []
    raw_segments = getattr(response, "segments", None) or []
    for seg in raw_segments:
        # SDK returns objects with attribute access; keep .get-style access
        # working too in case a future SDK version returns dicts.
        getter = (
            (lambda s, key: getattr(s, key, None))
            if not isinstance(seg, dict)
            else (lambda s, key: s.get(key))
        )
        segments_out.append(
            {
                "start": getter(seg, "start"),
                "end": getter(seg, "end"),
                "text": (getter(seg, "text") or "").strip()
                if getter(seg, "text")
                else "",
            }
        )

    return {
        "text": text,
        "language": detected_language,
        "segments": segments_out,
    }
