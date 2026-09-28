import pytest
from types import SimpleNamespace

from app.services.storage.audio_delivery import (
    collect_evaluator_result_audio_keys,
    stream_audio_from_keys,
)


def test_collect_evaluator_result_audio_keys_deduplicates():
    result = SimpleNamespace(
        audio_s3_key="audio/org/a.wav",
        call_data={"recording_s3_key": "audio/org/a.wav"},
    )
    assert collect_evaluator_result_audio_keys(result) == ["audio/org/a.wav"]

    result2 = SimpleNamespace(
        audio_s3_key="audio/org/a.wav",
        call_data={"recording_s3_key": "audio/org/b.wav"},
    )
    assert collect_evaluator_result_audio_keys(result2) == ["audio/org/a.wav", "audio/org/b.wav"]


def test_stream_audio_from_keys_falls_back_to_second_key(monkeypatch):
    calls: list[str] = []

    def _iter_chunks(key, chunk_size=8192):
        calls.append(key)
        if key == "missing.wav":
            from app.core.exceptions import StorageError

            raise StorageError("missing")
        yield b"audio-bytes"

    fake = SimpleNamespace(
        is_enabled=lambda: True,
        iter_file_chunks_by_key=_iter_chunks,
        download_file_by_key=lambda _key: b"audio-bytes",
    )
    monkeypatch.setattr(
        "app.services.storage.audio_delivery.blob_storage_service",
        fake,
    )

    response = stream_audio_from_keys(["missing.wav", "present.wav"], filename="call_1")
    assert response is not None
    assert calls == ["missing.wav", "present.wav"]


def test_stream_audio_from_keys_returns_none_when_all_missing(monkeypatch):
    def _iter_chunks(_key, chunk_size=8192):
        from app.core.exceptions import StorageError

        raise StorageError("missing")

    fake = SimpleNamespace(
        is_enabled=lambda: True,
        iter_file_chunks_by_key=_iter_chunks,
        download_file_by_key=lambda _key: (_ for _ in ()).throw(StorageError("missing")),
    )
    monkeypatch.setattr(
        "app.services.storage.audio_delivery.blob_storage_service",
        fake,
    )

    assert stream_audio_from_keys(["a.wav"], filename="call_1") is None
