"""Scatter-gather helpers."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.db_sharding.scatter_gather import fetch_call_import_rows_page


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
