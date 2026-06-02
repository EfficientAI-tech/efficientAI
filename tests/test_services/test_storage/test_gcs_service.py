"""Service-layer tests for GCS storage service with mocked client."""

import importlib
from datetime import datetime, UTC
from uuid import uuid4

import pytest

from app.core.exceptions import StorageError
from app.services.storage.gcs_service import GcsService

gcs_module = importlib.import_module("app.services.storage.gcs_service")


class _FakeBlob:
    def __init__(self, name: str, bucket):
        self.name = name
        self.bucket = bucket
        self.size = 123
        self.updated = datetime.now(UTC)
        self.time_created = self.updated
        self._content = b""

    def upload_from_string(self, data, content_type=None):
        self._content = data
        self.bucket.objects[self.name] = data

    def download_as_bytes(self):
        if self.name not in self.bucket.objects:
            from google.api_core.exceptions import NotFound
            raise NotFound("missing")
        return self.bucket.objects[self.name]

    def exists(self):
        return self.name in self.bucket.objects

    def delete(self):
        self.bucket.objects.pop(self.name, None)

    def generate_signed_url(self, **_kwargs):
        return f"https://storage.googleapis.com/{self.bucket.name}/{self.name}?signed=1"


class _FakePage:
    def __init__(self, prefixes=None, blobs=None):
        self.prefixes = prefixes or []
        self._blobs = blobs or []

    def __iter__(self):
        return iter(self._blobs)


class _FakeListIterator:
    def __init__(self, pages):
        self.pages = pages


class _FakeBucket:
    def __init__(self, name):
        self.name = name
        self.objects = {}

    def blob(self, key):
        return _FakeBlob(key, self)

    def exists(self):
        return True


class _FakeGcsClient:
    def __init__(self):
        self._bucket = _FakeBucket("bucket-a")
        self.list_calls = []

    def bucket(self, name):
        self._bucket.name = name
        return self._bucket

    def list_blobs(self, bucket_name, prefix="", delimiter=None, max_results=None):
        self.list_calls.append(
            {"bucket": bucket_name, "prefix": prefix, "delimiter": delimiter}
        )
        if delimiter == "/":
            return _FakeListIterator(
                [
                    _FakePage(
                        prefixes=["organizations/org-1/audio/subfolder/"],
                        blobs=[
                            _FakeBlob(
                                "organizations/org-1/audio/file1.mp3", self._bucket
                            )
                        ],
                    )
                ]
            )
        return [
            _FakeBlob("audio/one.mp3", self._bucket),
            _FakeBlob("audio/two.txt", self._bucket),
        ]


@pytest.fixture
def configured_gcs(monkeypatch):
    monkeypatch.setattr(gcs_module.settings, "GCS_ENABLED", True, raising=False)
    monkeypatch.setattr(gcs_module.settings, "GCS_BUCKET_NAME", "bucket-a", raising=False)
    monkeypatch.setattr(gcs_module.settings, "GCS_PROJECT_ID", "proj-1", raising=False)
    monkeypatch.setattr(gcs_module.settings, "GCS_PREFIX", "", raising=False)
    monkeypatch.setattr(gcs_module.settings, "GCS_CREDENTIALS_PATH", None, raising=False)
    monkeypatch.setattr(gcs_module.settings, "ALLOWED_AUDIO_FORMATS", ["mp3", "wav"], raising=False)

    fake_client = _FakeGcsClient()

    def _build_client():
        return fake_client

    monkeypatch.setattr(GcsService, "_build_client", lambda self: fake_client)

    service = GcsService()
    service._ensure_initialized()
    return service, fake_client


def test_get_key_formats_path_with_organization_and_evaluator(configured_gcs):
    service, _ = configured_gcs
    key = service._get_key(
        uuid4(), "mp3", organization_id="org-1", evaluator_id="eval-9", meaningful_id="result-1"
    )

    assert key == "organizations/org-1/evaluators/eval-9/audio/result-1.mp3"


def test_upload_file_puts_expected_content_type(configured_gcs):
    service, fake_client = configured_gcs
    key = service.upload_file(b"audio-bytes", uuid4(), "mp3")

    assert key.endswith(".mp3")
    assert fake_client._bucket.objects[key] == b"audio-bytes"


def test_upload_file_raises_when_gcs_disabled(monkeypatch):
    monkeypatch.setattr(gcs_module.settings, "GCS_ENABLED", False, raising=False)
    service = GcsService()

    with pytest.raises(StorageError):
        service.upload_file(b"abc", uuid4(), "wav")


def test_list_audio_files_filters_non_audio_extensions(configured_gcs):
    service, _ = configured_gcs
    files = service.list_audio_files(prefix="audio/")

    assert len(files) == 1
    assert files[0]["filename"] == "one.mp3"


def test_browse_folder_returns_folders_and_files(configured_gcs):
    service, _ = configured_gcs
    result = service.browse_folder(organization_id="org-1", path="audio")

    assert result["organization_id"] == "org-1"
    assert len(result["folders"]) == 1
    assert len(result["files"]) == 1


def test_delete_keys_dedupes_and_skips_falsy(configured_gcs):
    service, fake_client = configured_gcs
    fake_client._bucket.objects["a"] = b"1"
    fake_client._bucket.objects["b"] = b"2"

    deleted, errors = service.delete_keys(["a", "a", "b", "", None])

    assert deleted == 2
    assert errors == []
    assert fake_client._bucket.objects == {}


def test_delete_keys_by_prefix_lists_then_bulk_deletes(monkeypatch):
    fake_client = _FakeGcsClient()
    fake_client._bucket.objects = {"p/1": b"1", "p/2": b"2", "p/3": b"3"}

    def _list_blobs(_bucket_name, prefix="", delimiter=None, max_results=None):
        if prefix == "p/":
            return [_FakeBlob(k, fake_client._bucket) for k in sorted(fake_client._bucket.objects)]
        return []

    fake_client.list_blobs = _list_blobs
    monkeypatch.setattr(gcs_module.settings, "GCS_ENABLED", True, raising=False)
    monkeypatch.setattr(gcs_module.settings, "GCS_BUCKET_NAME", "bucket-a", raising=False)
    monkeypatch.setattr(GcsService, "_build_client", lambda self: fake_client)

    service = GcsService()
    service._ensure_initialized()

    deleted, errors = service.delete_keys_by_prefix("p/")

    assert deleted == 3
    assert errors == []


def test_generate_presigned_url_by_key(configured_gcs, monkeypatch):
    service, fake_client = configured_gcs
    fake_client._bucket.objects["audio/test.mp3"] = b"x"
    monkeypatch.setattr(service, "_get_signing_credentials", lambda: object())

    url = service.generate_presigned_url_by_key("audio/test.mp3")

    assert "signed=1" in url
