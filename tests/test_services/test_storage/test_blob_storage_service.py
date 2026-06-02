"""Tests for blob storage provider facade."""

import importlib
from uuid import uuid4

import pytest

blob_module = importlib.import_module("app.services.storage.blob_storage_service")


class _FakeBackend:
    def __init__(self, name: str):
        self.name = name
        self.prefix = f"{name}-prefix/"
        self.reset_called = False
        self.upload_calls = []

    def reset_connection(self):
        self.reset_called = True

    def is_enabled(self):
        return True

    def get_status_message(self):
        return None

    def upload_file(self, file_content, file_id, file_format, organization_id=None, evaluator_id=None, meaningful_id=None):
        self.upload_calls.append((file_content, file_id, file_format))
        return f"{self.name}/key.{file_format}"


@pytest.fixture
def facade_with_fakes(monkeypatch):
    fake_s3 = _FakeBackend("s3")
    fake_gcs = _FakeBackend("gcs")
    service = blob_module.BlobStorageService()
    service._s3 = fake_s3
    service._gcs = fake_gcs
    return service, fake_s3, fake_gcs


def test_provider_name_reflects_settings(monkeypatch, facade_with_fakes):
    service, _, _ = facade_with_fakes
    monkeypatch.setattr(blob_module.settings, "BLOB_STORAGE_PROVIDER", "gcs", raising=False)
    assert service.provider_name == "gcs"


def test_delegates_to_s3_when_provider_is_s3(monkeypatch, facade_with_fakes):
    service, fake_s3, fake_gcs = facade_with_fakes
    monkeypatch.setattr(blob_module.settings, "BLOB_STORAGE_PROVIDER", "s3", raising=False)

    file_id = uuid4()
    key = service.upload_file(b"data", file_id, "wav", organization_id="org-1")

    assert key == "s3/key.wav"
    assert fake_s3.upload_calls
    assert not fake_gcs.upload_calls


def test_delegates_to_gcs_when_provider_is_gcs(monkeypatch, facade_with_fakes):
    service, fake_s3, fake_gcs = facade_with_fakes
    monkeypatch.setattr(blob_module.settings, "BLOB_STORAGE_PROVIDER", "gcs", raising=False)

    file_id = uuid4()
    key = service.upload_file(b"data", file_id, "mp3")

    assert key == "gcs/key.mp3"
    assert fake_gcs.upload_calls
    assert not fake_s3.upload_calls


def test_reset_connection_resets_both_backends(facade_with_fakes):
    service, fake_s3, fake_gcs = facade_with_fakes

    service.reset_connection()

    assert fake_s3.reset_called is True
    assert fake_gcs.reset_called is True


def test_prefix_comes_from_active_backend(monkeypatch, facade_with_fakes):
    service, fake_s3, fake_gcs = facade_with_fakes
    monkeypatch.setattr(blob_module.settings, "BLOB_STORAGE_PROVIDER", "gcs", raising=False)

    assert service.prefix == fake_gcs.prefix
