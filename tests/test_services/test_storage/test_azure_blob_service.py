"""Service-layer tests for Azure Blob Storage service with mocked client."""

import importlib
from datetime import datetime, UTC
from uuid import uuid4

import pytest

from app.core.exceptions import StorageError
from app.services.storage.azure_blob_service import AzureBlobService

azure_module = importlib.import_module("app.services.storage.azure_blob_service")


class _FakeBlobProperties:
    def __init__(self, name: str, size: int = 123):
        self.name = name
        self.size = size
        self.last_modified = datetime.now(UTC)


class _FakePrefix:
    def __init__(self, prefix: str):
        self.prefix = prefix


class _FakeBlobClient:
    def __init__(self, name: str, container):
        self.name = name
        self.container = container
        self.url = f"https://account.blob.core.windows.net/{container.name}/{name}"

    def upload_blob(self, data, overwrite=True, content_type=None, content_settings=None, **kwargs):
        self.container.objects[self.name] = data

    def download_blob(self):
        if self.name not in self.container.objects:
            _, ResourceNotFoundError, _, _, _ = azure_module._get_azure_libs()
            raise ResourceNotFoundError("missing")

        class _Downloader:
            def __init__(self, content):
                self._content = content

            def readall(self):
                return self._content

        return _Downloader(self.container.objects[self.name])

    def exists(self):
        return self.name in self.container.objects

    def delete_blob(self):
        self.container.objects.pop(self.name, None)


class _FakeContainerClient:
    def __init__(self, name):
        self.name = name
        self.objects = {}
        self.delete_calls = []
        self.list_calls = []
        self.walk_calls = []

    def exists(self):
        return True

    def get_blob_client(self, key):
        return _FakeBlobClient(key, self)

    def delete_blobs(self, *keys):
        self.delete_calls.append(list(keys))
        for key in keys:
            self.objects.pop(key, None)

    def list_blobs(self, name_starts_with=""):
        self.list_calls.append(name_starts_with)
        return [
            _FakeBlobProperties("audio/one.mp3"),
            _FakeBlobProperties("audio/two.txt"),
        ]

    def walk_blobs(self, name_starts_with="", delimiter=None):
        self.walk_calls.append({"prefix": name_starts_with, "delimiter": delimiter})
        yield _FakePrefix(f"{name_starts_with}subfolder/")
        yield _FakeBlobProperties(f"{name_starts_with}file1.mp3")


class _FakeBlobServiceClient:
    account_name = "account"

    def __init__(self):
        self._container = _FakeContainerClient("container-a")

    def get_container_client(self, name):
        self._container.name = name
        return self._container


@pytest.fixture
def configured_azure(monkeypatch):
    monkeypatch.setattr(azure_module.settings, "AZURE_BLOB_ENABLED", True, raising=False)
    monkeypatch.setattr(
        azure_module.settings, "AZURE_CONTAINER_NAME", "container-a", raising=False
    )
    monkeypatch.setattr(
        azure_module.settings, "AZURE_ACCOUNT_NAME", "account", raising=False
    )
    monkeypatch.setattr(
        azure_module.settings,
        "AZURE_ACCOUNT_KEY",
        "YWJjZGVmZ2hpams=",  # base64("abcdefghijk") — valid for SAS signing in tests
        raising=False,
    )
    monkeypatch.setattr(azure_module.settings, "AZURE_CONNECTION_STRING", None, raising=False)
    monkeypatch.setattr(azure_module.settings, "AZURE_PREFIX", "", raising=False)
    monkeypatch.setattr(
        azure_module.settings, "ALLOWED_AUDIO_FORMATS", ["mp3", "wav"], raising=False
    )

    fake_client = _FakeBlobServiceClient()

    def _build_client():
        return fake_client

    monkeypatch.setattr(AzureBlobService, "_build_client", lambda self: fake_client)

    service = AzureBlobService()
    service._ensure_initialized()
    return service, fake_client


def test_get_key_formats_path_with_organization_and_evaluator(configured_azure):
    service, _ = configured_azure
    key = service._get_key(
        uuid4(), "mp3", organization_id="org-1", evaluator_id="eval-9", meaningful_id="result-1"
    )

    assert key == "organizations/org-1/evaluators/eval-9/audio/result-1.mp3"


def test_upload_file_puts_expected_content(configured_azure):
    service, fake_client = configured_azure
    key = service.upload_file(b"audio-bytes", uuid4(), "mp3")

    assert key.endswith(".mp3")
    assert fake_client._container.objects[key] == b"audio-bytes"


def test_upload_file_raises_when_azure_disabled(monkeypatch):
    monkeypatch.setattr(azure_module.settings, "AZURE_BLOB_ENABLED", False, raising=False)
    service = AzureBlobService()

    with pytest.raises(StorageError):
        service.upload_file(b"abc", uuid4(), "wav")


def test_list_audio_files_filters_non_audio_extensions(configured_azure):
    service, _ = configured_azure
    files = service.list_audio_files(prefix="audio/")

    assert len(files) == 1
    assert files[0]["filename"] == "one.mp3"


def test_browse_folder_returns_folders_and_files(configured_azure):
    service, _ = configured_azure
    result = service.browse_folder(organization_id="org-1", path="audio")

    assert result["organization_id"] == "org-1"
    assert len(result["folders"]) == 1
    assert len(result["files"]) == 1


def test_delete_keys_dedupes_and_skips_falsy(configured_azure):
    service, fake_client = configured_azure
    fake_client._container.objects["a"] = b"1"
    fake_client._container.objects["b"] = b"2"

    deleted, errors = service.delete_keys(["a", "a", "b", "", None])

    assert deleted == 2
    assert errors == []
    assert fake_client._container.objects == {}


def test_delete_keys_by_prefix_lists_then_bulk_deletes(monkeypatch):
    fake_client = _FakeBlobServiceClient()
    fake_client._container.objects = {"p/1": b"1", "p/2": b"2", "p/3": b"3"}

    def _list_blobs(name_starts_with=""):
        if name_starts_with == "p/":
            return [
                _FakeBlobProperties(k) for k in sorted(fake_client._container.objects)
            ]
        return []

    fake_client._container.list_blobs = _list_blobs
    monkeypatch.setattr(azure_module.settings, "AZURE_BLOB_ENABLED", True, raising=False)
    monkeypatch.setattr(
        azure_module.settings, "AZURE_CONTAINER_NAME", "container-a", raising=False
    )
    monkeypatch.setattr(
        azure_module.settings, "AZURE_ACCOUNT_NAME", "account", raising=False
    )
    monkeypatch.setattr(
        azure_module.settings,
        "AZURE_ACCOUNT_KEY",
        "YWJjZGVmZ2hpams=",  # base64("abcdefghijk") — valid for SAS signing in tests
        raising=False,
    )
    monkeypatch.setattr(AzureBlobService, "_build_client", lambda self: fake_client)

    service = AzureBlobService()
    service._ensure_initialized()

    deleted, errors = service.delete_keys_by_prefix("p/")

    assert deleted == 3
    assert errors == []


def test_generate_presigned_url_by_key(configured_azure):
    service, fake_client = configured_azure
    fake_client._container.objects["audio/test.mp3"] = b"x"

    url = service.generate_presigned_url_by_key("audio/test.mp3")

    assert "audio/test.mp3" in url
    assert "sig=" in url or "se=" in url or "?" in url
