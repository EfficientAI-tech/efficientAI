from unittest.mock import MagicMock
from uuid import UUID

import pytest

from app.services.synthetic_traces.span_storage import delete_trace_s3_wal_batches


@pytest.fixture
def trace_ids():
    return {
        "organization_id": UUID("11111111-1111-1111-1111-111111111111"),
        "workspace_id": UUID("22222222-2222-2222-2222-222222222222"),
        "trace_id": UUID("33333333-3333-3333-3333-333333333333"),
    }


def test_delete_trace_s3_wal_batches_uses_batches_prefix(monkeypatch, trace_ids):
    monkeypatch.setattr("app.config.settings.S3_ENABLED", True)
    monkeypatch.setattr("app.config.settings.TRACES_S3_PREFIX", "traces/")
    delete_mock = MagicMock(return_value=(2, []))
    monkeypatch.setattr(
        "app.services.synthetic_traces.span_storage.blob_storage_service.delete_keys_by_prefix",
        delete_mock,
    )

    deleted = delete_trace_s3_wal_batches(**trace_ids)

    assert deleted == 2
    delete_mock.assert_called_once_with(
        "traces/organizations/11111111-1111-1111-1111-111111111111/"
        "workspaces/22222222-2222-2222-2222-222222222222/"
        "traces/33333333-3333-3333-3333-333333333333/batches/"
    )


def test_delete_trace_s3_wal_batches_skips_when_s3_disabled(monkeypatch, trace_ids):
    monkeypatch.setattr("app.config.settings.S3_ENABLED", False)
    delete_mock = MagicMock()
    monkeypatch.setattr(
        "app.services.synthetic_traces.span_storage.blob_storage_service.delete_keys_by_prefix",
        delete_mock,
    )

    assert delete_trace_s3_wal_batches(**trace_ids) == 0
    delete_mock.assert_not_called()
