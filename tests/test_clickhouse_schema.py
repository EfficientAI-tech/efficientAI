"""ClickHouse client and schema helpers."""

from unittest.mock import MagicMock, patch

from app.services.clickhouse.client import clickhouse_enabled, reset_client_cache
from app.services.clickhouse.schema import ensure_schema


def test_clickhouse_enabled_false_when_url_missing():
    from app.config import settings

    original = settings.CLICKHOUSE_URL
    settings.CLICKHOUSE_URL = None
    try:
        assert clickhouse_enabled() is False
    finally:
        settings.CLICKHOUSE_URL = original


@patch("app.services.clickhouse.schema.get_client")
@patch("app.services.clickhouse.schema.clickhouse_enabled", return_value=True)
def test_ensure_schema_runs_ddl(mock_enabled, mock_get_client):
    client = MagicMock()
    client.database = "efficientai"
    mock_get_client.return_value = client
    ensure_schema()
    assert client.command.call_count >= 3
    reset_client_cache()
