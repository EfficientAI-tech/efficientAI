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
    evaluation = MagicMock(id=uuid4(), call_import_id=uuid4())
    shard_a = MagicMock(name="shard-a")
    shard_b = MagicMock(name="shard-b")
    er1 = MagicMock(id=uuid4(), status="failed")
    er2 = MagicMock(id=uuid4(), status="failed")
    seen = []

    def _sessions(_catalog, _import_id):
        yield shard_a, "shard-a"
        yield shard_b, "shard-b"

    def _page(session, _evaluation_id, **kwargs):
        seen.append(kwargs)
        if session is shard_a and kwargs.get("after_id") is None:
            return [(er1, MagicMock())]
        if session is shard_b and kwargs.get("after_id") is None:
            return [(er2, MagicMock())]
        return []

    with patch(
        "app.db_sharding.eval_rows.iter_evaluation_row_sessions",
        _sessions,
    ), patch(
        "app.db_sharding.eval_rows.load_retry_target_page",
        _page,
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
    assert seen
    assert all(call["status"] == "failed" for call in seen)
    assert all(call["include_metric_scores"] is False for call in seen)
    assert all(call["ordered"] is True for call in seen)
