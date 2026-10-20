"""Tests for sharded evaluation row read helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.db_sharding.eval_rows import (
    count_evaluation_rows_for_run,
    load_evaluation_rows_for_run,
)


def test_load_evaluation_rows_delegates_to_pairs():
    catalog_db = MagicMock()
    evaluation_id = uuid4()
    eval_row = MagicMock()
    source_row = MagicMock()

    with patch(
        "app.db_sharding.eval_rows.load_evaluation_row_pairs",
        return_value=[(eval_row, source_row)],
    ):
        rows = load_evaluation_rows_for_run(catalog_db, evaluation_id)

    assert rows == [eval_row]


def test_count_evaluation_rows_by_status():
    catalog_db = MagicMock()
    evaluation_id = uuid4()
    catalog_db.query.return_value.filter.return_value.filter.return_value.scalar.return_value = 1

    assert (
        count_evaluation_rows_for_run(
            catalog_db, evaluation_id, statuses=["completed"]
        )
        == 1
    )
    catalog_db.query.return_value.filter.return_value.filter.assert_called()
