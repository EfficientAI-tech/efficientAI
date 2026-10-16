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


def test_page_insert_commits_shards_immediately_and_only_queues_finalize(monkeypatch):
    from app.services.voice_providers.historical.base import HistoricalListItem

    call_import = MagicMock()
    call_import.id = uuid4()
    call_import.organization_id = uuid4()
    call_import.workspace_id = uuid4()
    call_import.provider = "vapi"
    call_import.max_calls = None

    db = MagicMock()
    locked = MagicMock()
    locked.total_rows = 0
    selected = MagicMock()
    selected.one.return_value = locked
    allocated = MagicMock()
    allocated.scalar.return_value = 1
    db.execute.side_effect = [selected, allocated]

    captured: dict = {}

    def _insert(_catalog_db, _call_import_id, mappings, **kwargs):
        captured["defer_commit"] = kwargs.get("defer_commit", False)
        captured["on_conflict_do_nothing"] = kwargs.get("on_conflict_do_nothing", False)
        captured["committed_before_insert"] = db.commit.called
        captured["count"] = len(mappings)
        return len(mappings), [MagicMock(name="should_not_be_kept")]

    monkeypatch.setattr("app.db_sharding.sessions.is_sharding_enabled", lambda: True)
    monkeypatch.setattr(
        "app.db_sharding.row_ops.bulk_insert_mappings_on_shards",
        _insert,
    )

    pending = _DiscoveryShardPending()
    from app.services.call_imports.platform_discovery import _reserve_and_insert_rows

    capped = _reserve_and_insert_rows(
        db,
        call_import,
        MagicMock(platform="vapi"),
        [HistoricalListItem(conversation_id="conv-1")],
        include_reimport=False,
        shard_pending=pending,
    )

    assert capped is False
    assert captured["defer_commit"] is False
    assert captured["on_conflict_do_nothing"] is True
    assert captured["committed_before_insert"] is True
    assert captured["count"] == 1
    assert pending.sessions == []
    assert len(pending.finalizes) == 1
    assert pending.finalizes[0]["row_count"] == 1


def test_remaining_capacity_counts_uncommitted_reservations():
    from app.services.call_imports.platform_discovery import _remaining_call_capacity

    assert _remaining_call_capacity(40, 50, 100) == 10
    assert _remaining_call_capacity(80, 20, 100) == 0
    assert _remaining_call_capacity(0, 0, None) is None
    assert _remaining_call_capacity(0, 5, 0) is None


def test_recovered_reservation_keeps_recording_date():
    from datetime import date
    from types import SimpleNamespace

    from app.services.call_imports.platform_discovery import _platform_import_row_mapping

    call_import = SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        workspace_id=uuid4(),
    )
    mapping = _platform_import_row_mapping(
        call_import,
        row_id=uuid4(),
        row_index=4,
        conversation_id="conv-9",
        provider="vapi",
        recording_date=date(2026, 5, 18),
        raw_columns={"agent_id": "agent-1", "started_at": "2026-05-18T10:00:00+00:00"},
    )
    assert mapping["recording_date"] == date(2026, 5, 18)
    assert mapping["raw_columns"]["agent_id"] == "agent-1"
    assert mapping["recording_url"] == "vapi://conversations/conv-9"


def test_page_insert_stops_when_reservations_fill_the_limit(monkeypatch):
    from datetime import datetime, timezone

    from app.services.voice_providers.historical.base import HistoricalListItem

    call_import = MagicMock()
    call_import.id = uuid4()
    call_import.organization_id = uuid4()
    call_import.workspace_id = uuid4()
    call_import.provider = "vapi"
    call_import.max_calls = 100

    db = MagicMock()
    locked = MagicMock()
    locked.total_rows = 40
    selected = MagicMock()
    selected.one.return_value = locked
    reserved = MagicMock()
    reserved.scalar.return_value = 90
    db.execute.side_effect = [selected, reserved]

    monkeypatch.setattr("app.db_sharding.sessions.is_sharding_enabled", lambda: True)

    from app.services.call_imports.platform_discovery import (
        _DiscoveryShardPending,
        _reserve_and_insert_rows,
    )

    capped = _reserve_and_insert_rows(
        db,
        call_import,
        MagicMock(platform="vapi"),
        [
            HistoricalListItem(
                conversation_id="conv-extra",
                started_at=datetime(2026, 5, 18, tzinfo=timezone.utc),
            )
        ],
        include_reimport=False,
        shard_pending=_DiscoveryShardPending(),
    )

    assert capped is True
    db.commit.assert_not_called()


def test_page_insert_saves_recording_date_on_the_reservation(monkeypatch):
    from datetime import datetime, timezone

    from app.services.voice_providers.historical.base import HistoricalListItem

    call_import = MagicMock()
    call_import.id = uuid4()
    call_import.organization_id = uuid4()
    call_import.workspace_id = uuid4()
    call_import.provider = "vapi"
    call_import.max_calls = 10

    db = MagicMock()
    locked = MagicMock()
    locked.total_rows = 0
    selected = MagicMock()
    selected.one.return_value = locked
    reserved = MagicMock()
    reserved.scalar.return_value = 0
    allocated = MagicMock()
    allocated.scalar.return_value = 1
    db.execute.side_effect = [selected, reserved, allocated]

    captured: dict = {}

    def _insert(_catalog_db, _call_import_id, mappings, **kwargs):
        captured["mappings"] = mappings
        return len(mappings), []

    monkeypatch.setattr("app.db_sharding.sessions.is_sharding_enabled", lambda: True)
    monkeypatch.setattr(
        "app.db_sharding.row_ops.bulk_insert_mappings_on_shards",
        _insert,
    )

    from app.services.call_imports.platform_discovery import (
        _DiscoveryShardPending,
        _reserve_and_insert_rows,
    )

    started = datetime(2026, 5, 18, 9, 30, tzinfo=timezone.utc)
    _reserve_and_insert_rows(
        db,
        call_import,
        MagicMock(platform="vapi"),
        [HistoricalListItem(conversation_id="conv-1", agent_id="agent-1", started_at=started)],
        include_reimport=False,
        shard_pending=_DiscoveryShardPending(),
    )

    ledger = db.add.call_args.args[0]
    assert ledger.recording_date.isoformat() == "2026-05-18"
    assert ledger.raw_columns["agent_id"] == "agent-1"
    assert captured["mappings"][0]["recording_date"].isoformat() == "2026-05-18"
    assert captured["mappings"][0]["raw_columns"]["started_at"] == started.isoformat()
