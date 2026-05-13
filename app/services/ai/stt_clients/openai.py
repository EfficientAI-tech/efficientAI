"""OpenAI batch transcription client (Whisper + GPT-4o transcription models)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def transcribe_openai(
    audio_file_path: str,
    model: str,
    api_key: str,
    language: Optional[str] = None,
) -> Dict[str, Any]:
    """Transcribe an audio file via the OpenAI Whisper / GPT-4o transcription API.

    Supports both response shapes the API exposes today:

    - ``whisper-1``: returns ``verbose_json`` with per-segment + per-word
      timestamps (we ask for ``timestamp_granularities=["word","segment"]``).
    - ``gpt-4o-transcribe`` / ``gpt-4o-mini-transcribe``: only ``json`` /
      ``text`` are supported and ``timestamp_granularities`` is rejected,
      so we fall back to a flat ``json`` response and synthesise a single
      segment downstream.

    Returns the standardised dict ``{"text", "language", "segments", "words"}``.
    """
    # Absolute import — resolves to the top-level ``openai`` SDK, *not*
    # this submodule, even though they share a name.
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("OpenAI library not installed. Install with: pip install openai")

    client = OpenAI(api_key=api_key)

    # The new GPT-4o transcription models do NOT accept verbose_json /
    # timestamp_granularities. Detect them by name so we send a request
    # the API will actually accept.
    is_gpt4o_transcribe = model.startswith("gpt-4o") and "transcribe" in model

    request_kwargs: Dict[str, Any] = {
        "model": model,
        "language": language,
    }
    if is_gpt4o_transcribe:
        request_kwargs["response_format"] = "json"
    else:
        request_kwargs["response_format"] = "verbose_json"
        request_kwargs["timestamp_granularities"] = ["word", "segment"]

    with open(audio_file_path, "rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            file=audio_file,
            **request_kwargs,
        )

    result: Dict[str, Any] = {
        "text": transcript.text if hasattr(transcript, "text") else str(transcript),
        "language": (
            getattr(transcript, "language", language)
            if language
            else getattr(transcript, "language", "en")
        ),
        "segments": [],
        "words": [],
    }

    raw_segments = (
        getattr(transcript, "segments", None)
        if hasattr(transcript, "segments")
        else (transcript.get("segments") if isinstance(transcript, dict) else None)
    )
    if raw_segments:
        for seg in raw_segments:
            if isinstance(seg, dict):
                result["segments"].append(
                    {"start": seg.get("start", 0), "end": seg.get("end", 0), "text": seg.get("text", "")}
                )
            else:
                result["segments"].append(
                    {"start": getattr(seg, "start", 0), "end": getattr(seg, "end", 0), "text": getattr(seg, "text", "")}
                )

    raw_words = (
        getattr(transcript, "words", None)
        if hasattr(transcript, "words")
        else (transcript.get("words") if isinstance(transcript, dict) else None)
    )
    if raw_words:
        for w in raw_words:
            if isinstance(w, dict):
                result["words"].append(
                    {"word": w.get("word", ""), "start": w.get("start", 0) or 0, "end": w.get("end", 0) or 0}
                )
            else:
                word_start = getattr(w, "start", None)
                if word_start is None:
                    word_start = getattr(w, "start_time", 0) or 0
                word_end = getattr(w, "end", None)
                if word_end is None:
                    word_end = getattr(w, "end_time", 0) or 0
                result["words"].append(
                    {
                        "word": getattr(w, "word", "") or "",
                        "start": float(word_start) if word_start else 0.0,
                        "end": float(word_end) if word_end else 0.0,
                    }
                )

    # Synthesise a single segment when the API returned none (gpt-4o
    # transcribe variants, or sufficiently short clips).
    if not result["segments"] and result["text"]:
        import re

        sentences = [s.strip() for s in re.split(r"[.!?]+\s+", result["text"].strip()) if s.strip()]
        if sentences:
            current_time = 0.0
            for sentence in sentences:
                dur = max(0.5, (len(sentence.split()) / 150.0) * 60.0)
                result["segments"].append({"start": current_time, "end": current_time + dur, "text": sentence})
                current_time += dur
        else:
            word_count = len(result["text"].split())
            est = max(1.0, (word_count / 150.0) * 60.0)
            result["segments"] = [{"start": 0.0, "end": est, "text": result["text"]}]

    return result
