"""Shard commit ordering for platform discovery."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.services.call_imports.platform_discovery import (
    _DiscoveryShardPending,
    _commit_catalog_with_pending_shards,
)


def test_commit_applies_finalize_only_after_shard_sessions(monkeypatch):
    db = MagicMock()
    pending = _DiscoveryShardPending()
    pending.sessions.append(MagicMock(name="shard_session"))
    row_id = uuid4()
    import_id = uuid4()
    pending.add_finalize(
        call_import_id=import_id,
        row_ids=[row_id],
        row_count=1,
        end_index=3,
    )

    commit_order: list[str] = []

    def _commit_sessions(sessions):
        commit_order.append("shards")
        assert sessions == pending.sessions

    def _apply(db_arg, finalizes):
        commit_order.append("finalize")
        assert len(finalizes) == 1

    monkeypatch.setattr(
        "app.db_sharding.row_ops.commit_pending_shard_sessions",
        _commit_sessions,
    )
    monkeypatch.setattr(
        "app.services.call_imports.platform_discovery._apply_shard_finalizes",
        _apply,
    )

    _commit_catalog_with_pending_shards(db, pending)

    assert commit_order == ["shards", "finalize"]
    db.commit.assert_called_once()
    assert pending.sessions == []
    assert pending.finalizes == []


def test_commit_shard_failure_clears_finalize_and_rolls_back_catalog(monkeypatch):
    db = MagicMock()
    pending = _DiscoveryShardPending()
    pending.sessions.append(MagicMock())
    pending.add_finalize(
        call_import_id=uuid4(),
        row_ids=[uuid4()],
        row_count=1,
        end_index=1,
    )

    def _fail(_sessions):
        raise RuntimeError("shard down")

    monkeypatch.setattr(
        "app.db_sharding.row_ops.commit_pending_shard_sessions",
        _fail,
    )
    monkeypatch.setattr(
        "app.db_sharding.row_ops.rollback_pending_shard_sessions",
        lambda _sessions: None,
    )

    with pytest.raises(RuntimeError, match="shard down"):
        _commit_catalog_with_pending_shards(db, pending)

    db.rollback.assert_called_once()
    db.commit.assert_not_called()
    assert pending.finalizes == []
