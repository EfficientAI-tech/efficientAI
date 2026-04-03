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
