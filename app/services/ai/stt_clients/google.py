"""Google (Gemini) batch transcription client routed through LiteLLM.

Unlike OpenAI/Deepgram/etc., Gemini does not expose a dedicated
``/audio/transcriptions`` endpoint. Instead we send the audio as an
``input_audio`` content block to ``litellm.completion`` and ask the
model to return a verbatim transcript. This keeps the call path
identical to the rest of our LiteLLM-backed services (see
``app.services.ai.llm_service.LLMService``).

Supported model keys in ``app/config/models.json``:

* ``gemini-2.5-pro-stt``       -> ``gemini/gemini-2.5-pro``
* ``gemini-2.5-flash-stt``     -> ``gemini/gemini-2.5-flash``
* ``gemini-2.5-flash-lite-stt``-> ``gemini/gemini-2.5-flash-lite``

The ``-stt`` suffix only exists in our config (so the same Gemini
family can appear as both ``llm`` and ``stt`` entries); we strip it
before handing the model name to LiteLLM.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# Audio file extensions accepted by Gemini's inline audio input.
# Mapped to the ``format`` string LiteLLM expects in ``input_audio``.
_GEMINI_AUDIO_FORMATS = {
    "wav": "wav",
    "mp3": "mp3",
    "aiff": "aiff",
    "aif": "aiff",
    "aac": "aac",
    "ogg": "ogg",
    "oga": "ogg",
    "flac": "flac",
    "m4a": "mp3",  # m4a/aac container; Gemini accepts as aac/mp3 in practice
    "webm": "webm",
    "mp4": "mp3",  # audio-only mp4; coerce to mp3 framing
}


def _strip_stt_suffix(model: Optional[str]) -> str:
    """Map our config keys (``gemini-2.5-flash-stt``) -> Gemini's
    real model name (``gemini-2.5-flash``)."""
    cleaned = (model or "").strip()
    if not cleaned:
        return "gemini-2.5-flash"
    if cleaned.endswith("-stt"):
        cleaned = cleaned[: -len("-stt")]
    return cleaned or "gemini-2.5-flash"


def _detect_audio_format(audio_file_path: str) -> str:
    """Derive the ``format`` field for LiteLLM's ``input_audio`` block.

    Defaults to ``wav`` when the extension is unknown — Gemini is
    fairly forgiving about format hints when the bytes are valid.
    """
    ext = Path(audio_file_path).suffix.lstrip(".").lower()
    return _GEMINI_AUDIO_FORMATS.get(ext, "wav")


def _build_transcription_prompt(language: Optional[str]) -> str:
    """Build a short, deterministic instruction so Gemini behaves like
    a transcription endpoint and only emits the transcript text."""
    if language:
        return (
            f"Transcribe the following audio verbatim in {language}. "
            "Return ONLY the transcript text, with no preamble, no "
            "speaker labels, no timestamps, and no markdown formatting."
        )
    return (
        "Transcribe the following audio verbatim in its original "
        "language. Return ONLY the transcript text, with no preamble, "
        "no speaker labels, no timestamps, and no markdown formatting."
    )


def transcribe_google(
    audio_file_path: str,
    model: str,
    api_key: str,
    language: Optional[str] = None,
) -> Dict[str, Any]:
    """Transcribe an audio file via Gemini through LiteLLM.

    Matches the ``transcribe_<provider>`` contract used elsewhere under
    :mod:`app.services.ai.stt_clients` so it can be dispatched from
    :class:`app.services.ai.transcription_service.TranscriptionService`
    without special-casing the response shape.
    """
    import litellm

    # LiteLLM silently drops params unsupported by the target provider
    # rather than raising — same setting we use in ``LLMService``.
    litellm.drop_params = True

    gemini_model = _strip_stt_suffix(model)
    litellm_model = f"gemini/{gemini_model}"
    audio_format = _detect_audio_format(audio_file_path)

    with open(audio_file_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("utf-8")

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": _build_transcription_prompt(language)},
                {
                    "type": "input_audio",
                    "input_audio": {"data": encoded, "format": audio_format},
                },
            ],
        }
    ]

    try:
        response = litellm.completion(
            model=litellm_model,
            messages=messages,
            api_key=api_key,
            temperature=0.0,
        )
    except Exception as e:
        logger.error(
            f"[transcribe_google] LiteLLM call failed for {litellm_model}: {e}"
        )
        raise RuntimeError(
            f"Gemini transcription failed for {litellm_model}: {e}"
        )

    text = ""
    try:
        text = (response.choices[0].message.content or "").strip()
    except (AttributeError, IndexError):
        text = ""

    return {
        "text": text,
        "language": language or "en",
        "segments": [],
    }
