"""Evaluation read helpers with multi-shard row data (integration-style)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.db_sharding.eval_rows import (
    find_evaluation_row_in_run,
    gather_retry_targets_sharded,
    load_evaluation_rows_for_run,
)


def test_load_evaluation_rows_from_scatter_pairs():
    catalog_db = MagicMock()
    evaluation_id = uuid4()
    er_a = MagicMock(id=uuid4())
    er_b = MagicMock(id=uuid4())

    with patch(
        "app.db_sharding.eval_rows.load_evaluation_row_pairs",
        return_value=[(er_a, MagicMock()), (er_b, MagicMock())],
    ):
        rows = load_evaluation_rows_for_run(catalog_db, evaluation_id)

    assert rows == [er_a, er_b]


def test_find_evaluation_row_in_run_two_shard_pairs():
    catalog_db = MagicMock()
    evaluation_id = uuid4()
    target_id = uuid4()
    other_id = uuid4()
    target_row = MagicMock(id=target_id, evaluation_id=evaluation_id)
    other_row = MagicMock(id=other_id, evaluation_id=evaluation_id)

    with patch(
        "app.db_sharding.eval_rows.load_evaluation_row_pairs",
        return_value=[
            (other_row, MagicMock()),
            (target_row, MagicMock()),
        ],
    ):
        found, _source = find_evaluation_row_in_run(
            catalog_db, evaluation_id, target_id
        )

    assert found is target_row


def test_gather_retry_targets_failed_rows_from_two_shards():
    catalog_db = MagicMock()
    evaluation = MagicMock(id=uuid4())
    er1 = MagicMock(id=uuid4(), status="failed")
    er2 = MagicMock(id=uuid4(), status="failed")
    er3 = MagicMock(id=uuid4(), status="running")

    with patch(
        "app.db_sharding.eval_rows.load_evaluation_row_pairs",
        return_value=[
            (er1, MagicMock()),
            (er2, MagicMock()),
            (er3, MagicMock()),
        ],
    ):
        targets, skipped = gather_retry_targets_sharded(
            catalog_db,
            evaluation,
            requested_ids=None,
            include_completed=False,
        )

    assert len(targets) == 2
    assert {t[0].id for t in targets} == {er1.id, er2.id}
    assert skipped == []
