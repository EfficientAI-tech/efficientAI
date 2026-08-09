"""Scatter-gather helpers."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.db_sharding.scatter_gather import (
    fetch_call_import_rows_page,
    max_call_import_row_index,
)


def test_fetch_rows_page_when_sharding_off():
    call_import_id = uuid4()
    db = MagicMock()
    mock_rows = [MagicMock(row_index=0)]
    db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = (
        mock_rows
    )
    with patch("app.db_sharding.scatter_gather.is_sharding_enabled", return_value=False):
        out = fetch_call_import_rows_page(db, call_import_id, offset=0, limit=10)
    assert out == mock_rows


def test_max_call_import_row_index_when_sharding_off():
    call_import_id = uuid4()
    db = MagicMock()
    db.query.return_value.filter.return_value.scalar.return_value = 41
    with patch("app.db_sharding.scatter_gather.is_sharding_enabled", return_value=False):
        assert max_call_import_row_index(db, call_import_id) == 41


def test_max_call_import_row_index_scatter_gather():
    call_import_id = uuid4()
    db = MagicMock()

    with patch("app.db_sharding.scatter_gather.is_sharding_enabled", return_value=True):
        with patch(
            "app.db_sharding.scatter_gather.shard_ids_for_import",
            return_value=["s1", "s2"],
        ):
            with patch(
                "app.db_sharding.scatter_gather.scatter_gather_on_shards",
                return_value=[10, 25],
            ):
                assert max_call_import_row_index(db, call_import_id) == 25
