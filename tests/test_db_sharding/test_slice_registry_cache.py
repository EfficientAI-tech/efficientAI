"""Slice-registry reads are cached until slices are written or rebalanced."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from app.db_sharding import registry as registry_module
from app.db_sharding.registry import (
    clear_slice_registry_cache,
    invalidate_slice_registry,
    load_slice_registry_for_import,
    publish_slice_registry_change,
)
from app.db_sharding.rebalance import (
    SliceInfo,
    _update_slice_registry,
    execute_rebalance_slices,
)
from app.db_sharding.row_ops import register_shard_slices


class _EpochRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key):
        return self.values.get(key, "0")

    def incr(self, key):
        current = int(self.values.get(key, "0")) + 1
        self.values[key] = str(current)
        return current


def setup_function() -> None:
    clear_slice_registry_cache()
    registry_module._epoch_client_override = _EpochRedis()


def teardown_function() -> None:
    registry_module._epoch_client_override = None
    clear_slice_registry_cache()


def _db_returning(rows):
    db = MagicMock()
    db.execute.return_value.all.return_value = rows
    return db


def test_slice_registry_is_cached_including_empty_maps():
    call_import_id = uuid4()
    db = _db_returning([])

    first = load_slice_registry_for_import(db, call_import_id)
    second = load_slice_registry_for_import(db, call_import_id)

    assert first == {}
    assert second == {}
    assert db.execute.call_count == 1


def test_invalidate_slice_registry_forces_reload():
    call_import_id = uuid4()
    db = _db_returning([(0, "shard-a")])

    first = load_slice_registry_for_import(db, call_import_id)
    invalidate_slice_registry(call_import_id)
    second = load_slice_registry_for_import(db, call_import_id)

    assert first[(str(call_import_id), 0)] == "shard-a"
    assert second[(str(call_import_id), 0)] == "shard-a"
    assert db.execute.call_count == 2


def test_register_shard_slices_drops_cache(monkeypatch):
    call_import_id = uuid4()
    db = _db_returning([])
    load_slice_registry_for_import(db, call_import_id)

    router = MagicMock()
    router.row_chunk_size = 500
    monkeypatch.setattr(
        "app.db_sharding.row_ops.is_sharding_enabled", lambda: True
    )
    monkeypatch.setattr(
        "app.db_sharding.row_ops.router_for_import",
        lambda *_args, **_kwargs: (router, None),
    )

    register_shard_slices(db, call_import_id, total_rows=1)
    load_slice_registry_for_import(db, call_import_id)

    assert db.execute.call_count == 2


def test_rebalance_registry_write_drops_cache():
    call_import_id = uuid4()
    db = _db_returning([(0, "shard-a")])
    load_slice_registry_for_import(db, call_import_id)

    _update_slice_registry(
        db,
        call_import_id,
        [SliceInfo(slice_id=0, shard_id="shard-b", row_index_min=0, row_index_max=10)],
        to_shard_id="shard-b",
    )
    load_slice_registry_for_import(db, call_import_id)

    assert db.execute.call_count == 2


def test_shared_epoch_change_reloads_without_a_local_invalidate():
    call_import_id = uuid4()
    db = _db_returning([(0, "shard-a")])

    load_slice_registry_for_import(db, call_import_id)
    registry_module._epoch_client_override.incr(
        f"shard:slice-registry:epoch:{call_import_id}"
    )
    load_slice_registry_for_import(db, call_import_id)

    assert db.execute.call_count == 2


def test_publish_slice_registry_change_bumps_the_shared_epoch():
    call_import_id = uuid4()
    db = _db_returning([(0, "shard-a")])
    load_slice_registry_for_import(db, call_import_id)

    publish_slice_registry_change(call_import_id)
    load_slice_registry_for_import(db, call_import_id)

    epoch = registry_module._epoch_client_override.get(
        f"shard:slice-registry:epoch:{call_import_id}"
    )
    assert epoch == "1"
    assert db.execute.call_count == 2


def test_rebalance_publishes_placement_before_deleting_source_rows(monkeypatch):
    order = []
    plan = MagicMock()
    plan.call_import_id = uuid4()
    plan.from_shard_id = "shard-a"
    plan.to_shard_id = "shard-b"
    plan.slices = [
        SliceInfo(slice_id=0, shard_id="shard-a", row_index_min=0, row_index_max=10)
    ]
    plan.import_row_count = 1
    plan.eval_row_count = 0

    monkeypatch.setattr(
        "app.db_sharding.rebalance._require_sharding", lambda: None
    )
    monkeypatch.setattr(
        "app.db_sharding.rebalance.assert_import_rebalance_ready",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "app.db_sharding.rebalance.acquire_rebalance_lock",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "app.db_sharding.rebalance.release_rebalance_lock",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "app.db_sharding.rebalance._copy_rows_between_shards",
        lambda **_kwargs: (1, 0, ["row-1"], []),
    )
    monkeypatch.setattr(
        "app.db_sharding.rebalance._update_slice_registry",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "app.db_sharding.rebalance.publish_slice_registry_change",
        lambda _call_import_id: order.append("publish"),
    )
    monkeypatch.setattr(
        "app.db_sharding.rebalance._delete_rows_from_source_shard",
        lambda **_kwargs: order.append("delete"),
    )
    catalog = MagicMock()
    catalog.commit.side_effect = lambda: order.append("commit")

    execute_rebalance_slices(catalog, plan)

    assert order == ["commit", "publish", "delete"]
