"""Service-layer tests for transcription service."""

import importlib
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.enums import ModelProvider
from app.services.ai.transcription_service import TranscriptionService

transcription_module = importlib.import_module("app.services.ai.transcription_service")
stt_clients_module = importlib.import_module("app.services.ai.stt_clients")


def test_transcribe_releases_read_session_before_provider_call(monkeypatch, tmp_path):
    service = TranscriptionService()
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"not-audio")
    events = []

    monkeypatch.setattr(
        service,
        "_download_audio_to_temp",
        lambda *_args, **_kwargs: str(audio),
    )
    monkeypatch.setattr(service, "_get_api_key_for_provider", lambda *_args, **_kwargs: "key-1")
    monkeypatch.setattr(
        service,
        "_get_credential_context_for_provider",
        lambda *_args, **_kwargs: None,
    )

    def _fake_openai(*_args, **_kwargs):
        events.append("http")
        return {"text": "hello", "duration": 1}

    monkeypatch.setattr(stt_clients_module, "transcribe_openai", _fake_openai)
    monkeypatch.setattr(
        "app.services.usage.llm_usage.record_stt_usage",
        lambda *_args, **_kwargs: None,
    )
    db = SimpleNamespace(
        new=[],
        dirty=[],
        deleted=[],
        rollback=lambda: events.append("rollback"),
    )
    result = service.transcribe(
        audio_file_key="org/clip.wav",
        stt_provider=ModelProvider.OPENAI,
        stt_model="whisper-1",
        organization_id=uuid4(),
        db=db,
        enable_speaker_diarization=False,
    )
    assert result["transcript"] == "hello"
    assert events == ["rollback", "http"]


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


def test_transcribe_text_only_strips_openai_text(monkeypatch):
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


def test_transcribe_text_only_uses_smallest_for_smallest_provider(monkeypatch):
    service = TranscriptionService()
    monkeypatch.setattr(service, "_get_api_key_for_provider", lambda *_args, **_kwargs: "key-1")
    monkeypatch.setattr(
        stt_clients_module,
        "transcribe_smallest",
        lambda *_args, **_kwargs: {"text": "  smallest transcript  "},
    )

    result = service.transcribe_text_only(
        audio_file_path="/tmp/a.wav",
        stt_provider=ModelProvider.SMALLEST,
        stt_model="pulse-v4",
        organization_id=uuid4(),
        db=object(),
    )
    assert result == "smallest transcript"


def test_transcribe_text_only_passes_language_for_sarvam(monkeypatch):
    service = TranscriptionService()
    monkeypatch.setattr(service, "_get_api_key_for_provider", lambda *_args, **_kwargs: "key-1")

    captured = {}

    def _fake_transcribe_sarvam(audio_file_path, model, api_key, language=None):
        captured["language"] = language
        return {"text": "namaste"}

    monkeypatch.setattr(
        stt_clients_module,
        "transcribe_sarvam",
        _fake_transcribe_sarvam,
    )

    result = service.transcribe_text_only(
        audio_file_path="/tmp/a.wav",
        stt_provider=ModelProvider.SARVAM,
        stt_model="saarika-v2.5",
        organization_id=uuid4(),
        db=object(),
        language="hi-IN",
    )
    assert result == "namaste"
    assert captured["language"] == "hi-IN"


def test_transcribe_text_only_returns_none_when_text_missing(monkeypatch):
    service = TranscriptionService()
    monkeypatch.setattr(service, "_get_api_key_for_provider", lambda *_args, **_kwargs: "key-1")
    monkeypatch.setattr(
        stt_clients_module,
        "transcribe_openai",
        lambda *_args, **_kwargs: {
            "language": "en",
            "segments": [],
        },
    )

    result = service.transcribe_text_only(
        audio_file_path="/tmp/a.wav",
        stt_provider=ModelProvider.OPENAI,
        stt_model="whisper-1",
        organization_id=uuid4(),
        db=object(),
    )
    assert result is None
