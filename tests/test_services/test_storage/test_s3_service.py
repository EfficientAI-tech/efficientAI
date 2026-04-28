"""Service-layer tests for S3 storage service with mocked client."""

import importlib
from datetime import datetime, UTC
from uuid import uuid4

import pytest

from app.core.exceptions import StorageError
from app.services.storage.s3_service import S3Service

s3_module = importlib.import_module("app.services.storage.s3_service")


class _FakeBody:
    def __init__(self, content: bytes):
        self._content = content

    def read(self):
        return self._content


class _FakeS3Client:
    def __init__(self):
        self.put_calls = []
        self.objects = {}

    def head_bucket(self, **_kwargs):
        return {}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.put_calls.append({"bucket": Bucket, "key": Key, "content_type": ContentType})
        self.objects[Key] = Body
        return {}

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise StorageError(f"Missing key {Key}")
        return {"Body": _FakeBody(self.objects[Key])}

    def list_objects_v2(self, **kwargs):
        if kwargs.get("Delimiter") == "/":
            return {
                "CommonPrefixes": [{"Prefix": "organizations/org-1/audio/subfolder/"}],
                "Contents": [
                    {"Key": "organizations/org-1/audio/file1.mp3", "Size": 123, "LastModified": datetime.now(UTC)},
                ],
            }
        return {
            "Contents": [
                {"Key": "audio/one.mp3", "Size": 100, "LastModified": datetime.now(UTC)},
                {"Key": "audio/two.txt", "Size": 100, "LastModified": datetime.now(UTC)},
            ]
        }

    def delete_object(self, **_kwargs):
        return {}

    def head_object(self, **_kwargs):
        return {}

    def generate_presigned_url(self, _operation, Params, ExpiresIn):
        return f"https://example.test/{Params['Key']}?exp={ExpiresIn}"


@pytest.fixture
def configured_s3(monkeypatch):
    monkeypatch.setattr(s3_module.settings, "S3_ENABLED", True, raising=False)
    monkeypatch.setattr(s3_module.settings, "S3_BUCKET_NAME", "bucket-a", raising=False)
    monkeypatch.setattr(s3_module.settings, "S3_REGION", "us-east-1", raising=False)
    monkeypatch.setattr(s3_module.settings, "S3_PREFIX", "", raising=False)
    monkeypatch.setattr(s3_module.settings, "S3_ACCESS_KEY_ID", "key", raising=False)
    monkeypatch.setattr(s3_module.settings, "S3_SECRET_ACCESS_KEY", "secret", raising=False)
    monkeypatch.setattr(s3_module.settings, "S3_ENDPOINT_URL", None, raising=False)
    monkeypatch.setattr(s3_module.settings, "ALLOWED_AUDIO_FORMATS", ["mp3", "wav"], raising=False)

    fake_client = _FakeS3Client()
    monkeypatch.setattr(s3_module.boto3, "client", lambda *_args, **_kwargs: fake_client)

    service = S3Service()
    service._ensure_initialized()
    return service, fake_client


def test_get_key_formats_path_with_organization_and_evaluator(configured_s3):
    service, _ = configured_s3
    key = service._get_key(uuid4(), "mp3", organization_id="org-1", evaluator_id="eval-9", meaningful_id="result-1")

    assert key == "organizations/org-1/evaluators/eval-9/audio/result-1.mp3"


def test_upload_file_puts_expected_content_type(configured_s3):
    service, fake_client = configured_s3
    key = service.upload_file(b"audio-bytes", uuid4(), "mp3")

    assert key.endswith(".mp3")
    assert fake_client.put_calls[-1]["content_type"] == "audio/mpeg"


def test_upload_file_raises_when_s3_disabled(monkeypatch):
    monkeypatch.setattr(s3_module.settings, "S3_ENABLED", False, raising=False)
    service = S3Service()

    with pytest.raises(StorageError):
        service.upload_file(b"abc", uuid4(), "wav")


def test_list_audio_files_filters_non_audio_extensions(configured_s3):
    service, _ = configured_s3
    files = service.list_audio_files(prefix="audio/")

    assert len(files) == 1
    assert files[0]["filename"] == "one.mp3"


def test_browse_folder_returns_folders_and_files(configured_s3):
    service, _ = configured_s3
    result = service.browse_folder(organization_id="org-1", path="audio")

    assert result["organization_id"] == "org-1"
    assert len(result["folders"]) == 1
    assert len(result["files"]) == 1


# ---------------------------------------------------------------------------
# delete_keys / delete_keys_by_prefix
# ---------------------------------------------------------------------------


class _RecordingDeleteClient(_FakeS3Client):
    """Variant that captures delete_objects payloads and lets tests inject errors/listings."""

    def __init__(self, list_pages=None, delete_errors=None):
        super().__init__()
        self.delete_object_calls = []
        self.delete_objects_calls = []
        self._list_pages = list_pages or []
        self._delete_errors = delete_errors or {}

    def delete_object(self, **kwargs):
        self.delete_object_calls.append(kwargs)
        return {}

    def delete_objects(self, Bucket, Delete):
        self.delete_objects_calls.append({"Bucket": Bucket, "Delete": Delete})
        keys = [obj["Key"] for obj in Delete.get("Objects", [])]
        errs = [
            {"Key": k, "Code": "AccessDenied", "Message": "nope"}
            for k in keys
            if k in self._delete_errors
        ]
        return {"Errors": errs} if errs else {}

    def get_paginator(self, _operation):
        client = self

        class _Paginator:
            def paginate(self, **_kwargs):
                return iter(client._list_pages)

        return _Paginator()


def _configure_with(monkeypatch, fake_client):
    monkeypatch.setattr(s3_module.settings, "S3_ENABLED", True, raising=False)
    monkeypatch.setattr(s3_module.settings, "S3_BUCKET_NAME", "bucket-a", raising=False)
    monkeypatch.setattr(s3_module.settings, "S3_REGION", "us-east-1", raising=False)
    monkeypatch.setattr(s3_module.settings, "S3_PREFIX", "", raising=False)
    monkeypatch.setattr(s3_module.settings, "S3_ACCESS_KEY_ID", "key", raising=False)
    monkeypatch.setattr(s3_module.settings, "S3_SECRET_ACCESS_KEY", "secret", raising=False)
    monkeypatch.setattr(s3_module.settings, "S3_ENDPOINT_URL", None, raising=False)
    monkeypatch.setattr(s3_module.boto3, "client", lambda *_a, **_kw: fake_client)
    service = S3Service()
    service._ensure_initialized()
    return service


def test_delete_keys_chunks_payloads_to_1000(monkeypatch):
    fake = _RecordingDeleteClient()
    service = _configure_with(monkeypatch, fake)

    keys = [f"k{i}" for i in range(2500)]
    deleted, errors = service.delete_keys(keys)

    assert deleted == 2500
    assert errors == []
    chunk_sizes = [len(c["Delete"]["Objects"]) for c in fake.delete_objects_calls]
    assert chunk_sizes == [1000, 1000, 500]


def test_delete_keys_dedupes_and_skips_falsy(monkeypatch):
    fake = _RecordingDeleteClient()
    service = _configure_with(monkeypatch, fake)

    deleted, errors = service.delete_keys(["a", "a", "b", "", None])

    assert deleted == 2
    assert errors == []
    payloads = fake.delete_objects_calls[0]["Delete"]["Objects"]
    assert sorted(o["Key"] for o in payloads) == ["a", "b"]


def test_delete_keys_returns_per_key_errors_without_raising(monkeypatch):
    fake = _RecordingDeleteClient(delete_errors={"bad-key"})
    service = _configure_with(monkeypatch, fake)

    deleted, errors = service.delete_keys(["good-1", "bad-key", "good-2"])

    assert deleted == 2
    assert len(errors) == 1
    assert errors[0]["Key"] == "bad-key"


def test_delete_keys_noop_for_empty_input(monkeypatch):
    fake = _RecordingDeleteClient()
    service = _configure_with(monkeypatch, fake)

    deleted, errors = service.delete_keys([])

    assert (deleted, errors) == (0, [])
    assert fake.delete_objects_calls == []


def test_delete_keys_by_prefix_lists_then_bulk_deletes(monkeypatch):
    pages = [
        {"Contents": [{"Key": "p/1"}, {"Key": "p/2"}]},
        {"Contents": [{"Key": "p/3"}]},
        {},  # empty page is OK
    ]
    fake = _RecordingDeleteClient(list_pages=pages)
    service = _configure_with(monkeypatch, fake)

    deleted, errors = service.delete_keys_by_prefix("p/")

    assert deleted == 3
    assert errors == []
    payload_keys = sorted(
        o["Key"] for o in fake.delete_objects_calls[0]["Delete"]["Objects"]
    )
    assert payload_keys == ["p/1", "p/2", "p/3"]


def test_delete_keys_by_prefix_returns_zero_when_no_matches(monkeypatch):
    fake = _RecordingDeleteClient(list_pages=[{"Contents": []}])
    service = _configure_with(monkeypatch, fake)

    deleted, errors = service.delete_keys_by_prefix("nothing-here/")

    assert (deleted, errors) == (0, [])
    assert fake.delete_objects_calls == []
