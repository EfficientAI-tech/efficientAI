"""Centralized STT provider API clients for batch / file-based transcription.

Every provider-specific HTTP or SDK call for transcribing an audio *file*
lives in this package, one provider per submodule.  ``TranscriptionService``
(and any other consumer) imports the ``transcribe_<provider>`` callables
re-exported here so endpoint URLs, header conventions, and SDK usage
patterns are defined in exactly one place per provider.

The streaming / real-time STT services under
``src/efficientai/services/<provider>/stt.py`` serve a different purpose
(WebSocket streams, frame pipelines) and are intentionally separate from
this package — the protocols, request shapes, and result shapes don't
share enough surface area to make a unified abstraction worthwhile.
"""

from .deepgram import transcribe_deepgram
from .elevenlabs import transcribe_elevenlabs
from .openai import transcribe_openai
from .sarvam import transcribe_sarvam
from .smallest import transcribe_smallest

__all__ = [
    "transcribe_deepgram",
    "transcribe_elevenlabs",
    "transcribe_openai",
    "transcribe_sarvam",
    "transcribe_smallest",
]
