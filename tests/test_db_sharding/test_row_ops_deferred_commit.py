"""Tests for deferred shard bulk-insert commit ordering."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.db_sharding.row_ops import (
    bulk_insert_mappings_on_shards,
    commit_pending_shard_sessions,
    rollback_pending_shard_sessions,
)


@patch("app.db_sharding.row_ops.is_sharding_enabled", return_value=True)
@patch("app.db_sharding.row_ops.partition_mappings_by_shard")
@patch("app.db_sharding.row_ops.db_pool_manager")
def test_bulk_insert_defer_commit_stages_without_closing_session(
    mock_pool_manager,
    mock_partition,
    _mock_sharding,
):
    shard_db = MagicMock()
    mock_pool_manager.shard_session_factory.return_value = lambda: shard_db
    mock_partition.return_value = {"shard-a": [{"row_index": 0}]}

    inserted, pending = bulk_insert_mappings_on_shards(
        MagicMock(),
        uuid4(),
        [{"row_index": 0}],
        defer_commit=True,
    )

    assert inserted == 1
    assert pending == [shard_db]
    shard_db.commit.assert_not_called()
    shard_db.close.assert_not_called()


@patch("app.db_sharding.row_ops.commit_shard_row_session")
@patch("app.db_sharding.row_ops._reset_shard_write_role")
def test_commit_pending_shard_sessions_commits_and_closes(
    _mock_reset,
    mock_commit,
):
    shard_db = MagicMock()
    commit_pending_shard_sessions([shard_db])
    mock_commit.assert_called_once_with(shard_db)
    shard_db.close.assert_called_once()


@patch("app.db_sharding.row_ops._reset_shard_write_role")
def test_rollback_pending_shard_sessions_rolls_back_and_closes(_mock_reset):
    shard_db = MagicMock()
    rollback_pending_shard_sessions([shard_db])
    shard_db.rollback.assert_called_once()
    shard_db.close.assert_called_once()
