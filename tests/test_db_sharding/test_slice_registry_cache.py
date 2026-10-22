"""Slice-registry reads are cached until slices are written or rebalanced."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from app.db_sharding.registry import (
    clear_slice_registry_cache,
    invalidate_slice_registry,
    load_slice_registry_for_import,
)
from app.db_sharding.rebalance import SliceInfo, _update_slice_registry
from app.db_sharding.row_ops import register_shard_slices


def setup_function() -> None:
    clear_slice_registry_cache()


def teardown_function() -> None:
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
