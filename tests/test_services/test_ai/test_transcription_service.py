"""Service-layer tests for transcription service."""

import importlib
from pathlib import Path
from uuid import uuid4

import pytest

from app.models.enums import ModelProvider
from app.services.ai.transcription_service import TranscriptionService

transcription_module = importlib.import_module("app.services.ai.transcription_service")
stt_clients_module = importlib.import_module("app.services.ai.stt_clients")


def test_transcribe_text_only_returns_none_when_no_api_key(monkeypatch):
    service = TranscriptionService()
    monkeypatch.setattr(service, "_get_api_key_for_provider", lambda *_args, **_kwargs: None)

    result = service.transcribe_text_only(
        audio_file_path="/tmp/a.wav",
        stt_provider=ModelProvider.OPENAI,
        stt_model="whisper-1",
        organization_id=uuid4(),
        db=object(),
    )
    assert result is None


def test_transcribe_text_only_openai_success(monkeypatch):
    service = TranscriptionService()
    monkeypatch.setattr(service, "_get_api_key_for_provider", lambda *_args, **_kwargs: "key-1")
    monkeypatch.setattr(
        stt_clients_module,
        "transcribe_openai",
        lambda *_args, **_kwargs: {"text": "  hello transcript  "},
    )

    result = service.transcribe_text_only(
        audio_file_path="/tmp/a.wav",
        stt_provider=ModelProvider.OPENAI,
        stt_model="whisper-1",
        organization_id=uuid4(),
        db=object(),
    )
    assert result == "hello transcript"


def test_transcribe_text_only_unsupported_provider_returns_none(monkeypatch):
    service = TranscriptionService()
    monkeypatch.setattr(service, "_get_api_key_for_provider", lambda *_args, **_kwargs: "key-1")

    result = service.transcribe_text_only(
        audio_file_path="/tmp/a.wav",
        stt_provider=ModelProvider.GOOGLE,
        stt_model="whatever",
        organization_id=uuid4(),
        db=object(),
    )
    assert result is None


def test_transcribe_returns_standard_shape_without_diarization(monkeypatch, tmp_path):
    service = TranscriptionService()
    temp_audio = tmp_path / "sample.wav"
    temp_audio.write_bytes(b"fake-audio")

    monkeypatch.setattr(service, "_download_audio_to_temp", lambda *_args, **_kwargs: str(temp_audio))
    monkeypatch.setattr(service, "_get_api_key_for_provider", lambda *_args, **_kwargs: "key-1")
    monkeypatch.setattr(
        stt_clients_module,
        "transcribe_openai",
        lambda *_args, **_kwargs: {
            "text": "hello world",
            "language": "en",
            "segments": [{"start": 0.0, "end": 1.0, "text": "hello world"}],
        },
    )

    result = service.transcribe(
        audio_file_key="audio-key",
        stt_provider=ModelProvider.OPENAI,
        stt_model="whisper-1",
        organization_id=uuid4(),
        db=object(),
        enable_speaker_diarization=False,
    )

    assert result["transcript"] == "hello world"
    assert result["language"] == "en"
    assert isinstance(result["segments"], list)
    assert result["speaker_segments"] is None
    assert not Path(temp_audio).exists()


def test_transcribe_raises_when_provider_key_missing(monkeypatch, tmp_path):
    service = TranscriptionService()
    temp_audio = tmp_path / "sample.wav"
    temp_audio.write_bytes(b"fake-audio")
    monkeypatch.setattr(service, "_download_audio_to_temp", lambda *_args, **_kwargs: str(temp_audio))
    monkeypatch.setattr(service, "_get_api_key_for_provider", lambda *_args, **_kwargs: None)

    with pytest.raises(RuntimeError, match="No API key found"):
        service.transcribe(
            audio_file_key="audio-key",
            stt_provider=ModelProvider.OPENAI,
            stt_model="whisper-1",
            organization_id=uuid4(),
            db=object(),
            enable_speaker_diarization=False,
        )
