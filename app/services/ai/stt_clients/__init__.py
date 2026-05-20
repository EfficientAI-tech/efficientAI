"""Batch / file-based Speech-to-Text clients.

Each ``transcribe_<provider>`` function follows the same minimal
contract::

    transcribe_<provider>(
        audio_file_path: str,
        model: str,
        api_key: str,
        language: Optional[str] = None,
    ) -> Dict[str, Any]

and returns a dict with at least a ``text`` key. ``language`` and
``segments`` may also be returned when the upstream provider supplies
them (or empty defaults otherwise).

These are deliberately *not* the realtime / frame-based STT services
under ``src/efficientai/services/...`` — those are for live audio
pipelines. This module is for offline, single-file transcription
(e.g. transcribing a recorded MP3 from S3 inside a Celery worker).
"""

from app.services.ai.stt_clients.deepgram import transcribe_deepgram
from app.services.ai.stt_clients.elevenlabs import transcribe_elevenlabs
from app.services.ai.stt_clients.google import transcribe_google
from app.services.ai.stt_clients.openai import transcribe_openai
from app.services.ai.stt_clients.sarvam import transcribe_sarvam
from app.services.ai.stt_clients.smallest import transcribe_smallest

__all__ = [
    "transcribe_deepgram",
    "transcribe_elevenlabs",
    "transcribe_google",
    "transcribe_openai",
    "transcribe_sarvam",
    "transcribe_smallest",
]
