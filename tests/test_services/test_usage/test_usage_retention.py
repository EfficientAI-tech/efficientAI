"""Tests for OSS usage history pruning."""

from datetime import date, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

from app.core.usage_entitlement import OSS_USAGE_HISTORY_DAYS
from app.services.usage.retention import oss_usage_cutoff_date, prune_oss_usage_history


def test_oss_usage_cutoff_inclusive_window():
    cutoff = oss_usage_cutoff_date()
    assert cutoff == date.today() - timedelta(days=OSS_USAGE_HISTORY_DAYS - 1)


def test_prune_skips_deployment_wide_license(monkeypatch):
    monkeypatch.setattr(
        "app.services.usage.retention.get_enabled_features",
        lambda: ["voice_playground"],
    )
    monkeypatch.setattr(
        "app.services.usage.retention.get_license_info",
        lambda: {"features": ["voice_playground"], "org_id": None},
    )
    mock_db = MagicMock()
    result = prune_oss_usage_history(mock_db)
    assert result["deleted"] == 0
    mock_db.query.assert_not_called()


def test_prune_deletes_old_rows_without_license(monkeypatch):
    monkeypatch.setattr("app.services.usage.retention.get_enabled_features", lambda: [])
    monkeypatch.setattr("app.services.usage.retention.get_license_info", lambda: {})

    mock_query = MagicMock()
    mock_query.filter.return_value = mock_query
    mock_query.delete.return_value = 3
    mock_db = MagicMock()
    mock_db.query.return_value = mock_query

    result = prune_oss_usage_history(mock_db)
    assert result["deleted"] == 3
    mock_db.commit.assert_called_once()


def test_prune_skips_entitled_org_when_license_org_scoped(monkeypatch):
    org_id = uuid4()
    monkeypatch.setattr(
        "app.services.usage.retention.get_enabled_features",
        lambda: ["call_imports"],
    )
    monkeypatch.setattr(
        "app.services.usage.retention.get_license_info",
        lambda: {
            "features": ["call_imports"],
            "org_id": str(org_id),
        },
    )

    mock_query = MagicMock()
    mock_query.filter.return_value = mock_query
    mock_query.delete.return_value = 0
    mock_db = MagicMock()
    mock_db.query.return_value = mock_query

    result = prune_oss_usage_history(mock_db)
    assert result["deleted"] == 0
    assert mock_query.filter.call_count == 2
