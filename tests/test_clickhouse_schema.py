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


@patch("app.services.clickhouse.schema._migrate_trace_observations_engine")
@patch("app.services.clickhouse.schema.get_client")
@patch("app.services.clickhouse.schema.clickhouse_enabled", return_value=True)
def test_ensure_schema_runs_ddl(mock_enabled, mock_get_client, mock_migrate_observations):
    client = MagicMock()
    client.database = "efficientai"
    mock_get_client.return_value = client
    ensure_schema()
    assert client.command.call_count >= 3
    mock_migrate_observations.assert_called_once_with(client)
    reset_client_cache()


@patch("app.services.clickhouse.schema.get_client")
def test_migrate_trace_observations_upgrades_legacy_mergetree(mock_get_client):
    from app.services.clickhouse.schema import _migrate_trace_observations_engine

    client = MagicMock()
    client.database = "efficientai"
    client.query.return_value = MagicMock(result_rows=[("MergeTree",)])
    mock_get_client.return_value = client

    _migrate_trace_observations_engine(client)

    rename_stmt = client.command.call_args_list[0].args[0]
    assert "RENAME TABLE trace_observations TO trace_observations__legacy_mergetree" in rename_stmt
    create_stmt = client.command.call_args_list[1].args[0]
    assert "CREATE TABLE trace_observations" in create_stmt
    assert "ReplacingMergeTree(received_at)" in create_stmt
    insert_stmt = client.command.call_args_list[2].args[0]
    assert "INSERT INTO trace_observations SELECT * FROM trace_observations__legacy_mergetree" in insert_stmt
    drop_stmt = client.command.call_args_list[3].args[0]
    assert drop_stmt == "DROP TABLE trace_observations__legacy_mergetree"


@patch("app.services.clickhouse.schema.get_client")
def test_migrate_trace_observations_skips_replacing_mergetree(mock_get_client):
    from app.services.clickhouse.schema import _migrate_trace_observations_engine

    client = MagicMock()
    client.database = "efficientai"
    client.query.return_value = MagicMock(result_rows=[("ReplacingMergeTree",)])
    mock_get_client.return_value = client

    _migrate_trace_observations_engine(client)

    client.command.assert_not_called()
