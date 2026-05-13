"""Deepgram batch transcription client (REST / prerecorded API)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _normalize_deepgram_model(model: Optional[str]) -> str:
    """Strip the ``deepgram-`` namespace prefix used in our models.json.

    The Deepgram API accepts model names like ``nova-3``, ``nova-2``,
    ``flux``, etc. We prefix them with ``deepgram-`` in ``models.json``
    to keep entries unique across providers. Sending the prefixed form
    to Deepgram's API yields a 403 "Project does not have access to
    the requested model" because the literal model ``deepgram-nova-3``
    doesn't exist on their side.
    """
    cleaned = (model or "").strip()
    if not cleaned:
        return "nova-2"
    if cleaned.startswith("deepgram-"):
        cleaned = cleaned[len("deepgram-"):]
    return cleaned or "nova-2"


def transcribe_deepgram(
    audio_file_path: str,
    model: str,
    api_key: str,
    language: Optional[str] = None,
) -> Dict[str, Any]:
    """Transcribe an audio file via the Deepgram REST (prerecorded) API.

    Uses the ``deepgram-sdk`` which is already a project dependency.
    """
    # Absolute import — resolves to the top-level ``deepgram`` SDK, *not*
    # this submodule.
    from deepgram import DeepgramClient

    client = DeepgramClient(api_key=api_key)

    with open(audio_file_path, "rb") as f:
        audio_bytes = f.read()

    options: Dict[str, Any] = {
        "model": _normalize_deepgram_model(model),
        "smart_format": True,
    }
    if language:
        options["language"] = language

    response = client.listen.rest.v("1").transcribe_file({"buffer": audio_bytes}, options)

    transcript = ""
    try:
        transcript = response.results.channels[0].alternatives[0].transcript
    except (AttributeError, IndexError):
        pass

    return {"text": transcript, "language": language or "en", "segments": []}
