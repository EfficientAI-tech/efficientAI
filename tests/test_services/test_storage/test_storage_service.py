"""Service-layer tests for local file storage service."""

import io
import importlib
from uuid import uuid4

import pytest

from app.core.exceptions import InvalidAudioFormatError, StorageError
from app.services.storage.storage_service import StorageService

storage_module = importlib.import_module("app.services.storage.storage_service")


def _upload_file(filename: str, content: bytes):
    return type("Upload", (), {"filename": filename, "file": io.BytesIO(content)})()


def test_validate_file_rejects_invalid_extension(monkeypatch, tmp_path):
    monkeypatch.setattr(storage_module.settings, "UPLOAD_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(storage_module.settings, "ALLOWED_AUDIO_FORMATS", ["wav", "mp3"], raising=False)
    service = StorageService()

    with pytest.raises(InvalidAudioFormatError, match="not allowed"):
        service.validate_file(_upload_file("voice.txt", b"abc"))


def test_save_file_persists_content(monkeypatch, tmp_path):
    monkeypatch.setattr(storage_module.settings, "UPLOAD_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(storage_module.settings, "ALLOWED_AUDIO_FORMATS", ["wav"], raising=False)
    monkeypatch.setattr(storage_module.settings, "MAX_FILE_SIZE_MB", 1, raising=False)
    service = StorageService()
    file_id = uuid4()

    saved_path, file_size = service.save_file(_upload_file("voice.wav", b"audio-data"), file_id)

    assert file_size == len(b"audio-data")
    assert io.open(saved_path, "rb").read() == b"audio-data"


def test_save_file_rejects_large_files(monkeypatch, tmp_path):
    monkeypatch.setattr(storage_module.settings, "UPLOAD_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(storage_module.settings, "ALLOWED_AUDIO_FORMATS", ["wav"], raising=False)
    monkeypatch.setattr(storage_module.settings, "MAX_FILE_SIZE_MB", 0.000001, raising=False)
    service = StorageService()

    with pytest.raises(StorageError, match="exceeds maximum allowed size"):
        service.save_file(_upload_file("voice.wav", b"this is too big"), uuid4())


def test_delete_file_returns_false_when_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(storage_module.settings, "UPLOAD_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(storage_module.settings, "ALLOWED_AUDIO_FORMATS", ["wav"], raising=False)
    service = StorageService()

    assert service.delete_file(uuid4(), "wav") is False
