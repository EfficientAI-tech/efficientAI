import pytest
from types import SimpleNamespace

from app.services.storage.audio_delivery import (
    collect_evaluator_result_audio_keys,
    stream_audio_from_keys,
    stream_audio_from_provider_url,
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


def test_stream_audio_from_provider_url_forwards_range(monkeypatch):
    import app.services.telephony.recording_download as recording_download

    monkeypatch.setattr(
        recording_download.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("52.0.0.1", 0))],
    )
    captured = {}

    class FakeResponse:
        status_code = 206
        headers = {
            "content-type": "audio/wav",
            "Content-Range": "bytes 0-1023/2048",
            "Accept-Ranges": "bytes",
        }

        def iter_content(self, chunk_size=8192):
            yield b"partial"

    def fake_get(url, headers=None, stream=True, timeout=60):
        captured["headers"] = headers
        return FakeResponse()

    monkeypatch.setattr("requests.get", fake_get)

    response = stream_audio_from_provider_url(
        "https://example.com/recording.wav",
        filename="call_1",
        range_header="bytes=0-1023",
    )

    assert response.status_code == 206
    assert captured["headers"]["Range"] == "bytes=0-1023"
    assert response.headers["Content-Range"] == "bytes 0-1023/2048"
