"""Service-layer tests for TTS service."""

import importlib
from uuid import uuid4

from app.models.enums import ModelProvider
from app.services.ai.tts_service import TTSService, get_audio_file_extension

tts_module = importlib.import_module("app.services.ai.tts_service")


def test_get_audio_file_extension_smallest_is_wav():
    assert get_audio_file_extension("smallest", 16000) == "wav"


def test_synthesize_smallest_dispatches_to_smallest_handler(monkeypatch):
    service = TTSService()
    monkeypatch.setattr(service, "_get_api_key_for_provider", lambda *_args, **_kwargs: "key-1")
    monkeypatch.setattr(
        tts_module,
        "synthesize_smallest_bytes",
        lambda **_kwargs: (b"smallest-audio", 12.3),
    )

    audio = service.synthesize(
        text="Hello from smallest",
        tts_provider=ModelProvider.SMALLEST,
        tts_model="lightning-v3.1",
        organization_id=uuid4(),
        db=object(),
        voice="daniel",
    )

    assert audio == b"smallest-audio"
