"""
Centralized STT provider API clients for batch / file-based transcription.

Every provider-specific HTTP or SDK call for transcribing an audio *file*
lives here.  ``TranscriptionService`` (and any future consumer) delegates
to these functions so that endpoint URLs, header conventions, and SDK
usage patterns are defined in exactly one place.

The streaming / real-time STT services under ``src/efficientai/services/``
serve a different purpose (WebSocket streams, frame pipelines) and are
intentionally separate.
"""

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

    Returns the standardised dict ``{"text", "language", "segments", "words"}``.
    """
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("OpenAI library not installed. Install with: pip install openai")

    client = OpenAI(api_key=api_key)

    with open(audio_file_path, "rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            model=model,
            file=audio_file,
            language=language,
            response_format="verbose_json",
            timestamp_granularities=["word", "segment"],
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

    # --- segments -----------------------------------------------------------
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

    # --- words --------------------------------------------------------------
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

    # Synthesise a single segment when the API returned none
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


def transcribe_deepgram(
    audio_file_path: str,
    model: str,
    api_key: str,
    language: Optional[str] = None,
) -> Dict[str, Any]:
    """Transcribe an audio file via the Deepgram REST (prerecorded) API.

    Uses the ``deepgram-sdk`` which is already a project dependency.
    """
    from deepgram import DeepgramClient

    client = DeepgramClient(api_key=api_key)

    with open(audio_file_path, "rb") as f:
        audio_bytes = f.read()

    options: Dict[str, Any] = {"model": model or "nova-2", "smart_format": True}
    if language:
        options["language"] = language

    response = client.listen.rest.v("1").transcribe_file({"buffer": audio_bytes}, options)

    transcript = ""
    try:
        transcript = response.results.channels[0].alternatives[0].transcript
    except (AttributeError, IndexError):
        pass

    return {"text": transcript, "language": language or "en", "segments": []}


def transcribe_elevenlabs(
    audio_file_path: str,
    model: str,
    api_key: str,
    language: Optional[str] = None,
) -> Dict[str, Any]:
    """Transcribe an audio file via the ElevenLabs Speech-to-Text REST API.

    Uses ``httpx`` for a synchronous POST (no ElevenLabs SDK in the project).
    The endpoint, headers, and form-field names are identical to those used by
    ``src/efficientai/services/elevenlabs/stt.py`` (async variant).
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


def transcribe_smallest(
    audio_file_path: str,
    model: str,
    api_key: str,
    language: Optional[str] = None,
) -> Dict[str, Any]:
    """Transcribe an audio file via Smallest Pulse (pre-recorded) REST API."""
    import httpx

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
