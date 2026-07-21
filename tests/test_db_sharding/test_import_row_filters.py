"""Sharded import row filter scatter-gather tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.db_sharding.scatter_gather import (
    fetch_call_import_rows_filtered_page,
    merge_rows_by_index,
)


def test_merge_rows_by_index_sorts():
    rows = [
        SimpleNamespace(row_index=2),
        SimpleNamespace(row_index=0),
        SimpleNamespace(row_index=1),
    ]
    ordered = merge_rows_by_index(rows)
    assert [int(r.row_index) for r in ordered] == [0, 1, 2]


def test_filtered_page_slices_merged_rows():
    catalog_db = MagicMock()
    call_import_id = uuid4()
    merged = [
        SimpleNamespace(row_index=0, id=uuid4()),
        SimpleNamespace(row_index=1, id=uuid4()),
        SimpleNamespace(row_index=2, id=uuid4()),
    ]

    with patch(
        "app.db_sharding.scatter_gather._merged_call_import_rows_for_import",
        return_value=merged,
    ):
        page = fetch_call_import_rows_filtered_page(
            catalog_db,
            call_import_id,
            search_term="foo",
            diarised_status_filter="completed",
            offset=1,
            limit=1,
        )

    assert len(page) == 1
    assert page[0].row_index == 1
