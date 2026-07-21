"""Tests for sharded eval-row pagination helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.db_sharding.eval_rows import fetch_evaluation_row_pairs_page


def _pair(row_index: int, status: str = "completed"):
    eval_row = SimpleNamespace(status=status, metric_scores={})
    source_row = SimpleNamespace(row_index=row_index, conversation_id=f"c-{row_index}")
    return eval_row, source_row


@patch("app.db_sharding.eval_rows.is_sharding_enabled", return_value=True)
@patch("app.db_sharding.eval_rows.scatter_gather_eval_query_count", return_value=4)
@patch("app.db_sharding.eval_rows.db_pool_manager")
def test_fetch_page_unbounded_sort_loads_all_shard_rows(
    mock_pool_manager,
    _mock_count,
    _mock_sharding,
):
    """Non-row_index sorts must not truncate per-shard results."""
    shard_a = MagicMock()
    shard_b = MagicMock()
    shard_a.all.return_value = [_pair(0, "failed"), _pair(1, "failed")]
    shard_b.all.return_value = [_pair(2, "completed"), _pair(3, "completed")]
    shard_a.limit.return_value = shard_a
    shard_b.limit.return_value = shard_b

    mock_pool_manager.router.shard_ids = ["shard-a", "shard-b"]
    session_a = MagicMock()
    session_b = MagicMock()

    def _factory(shard_id):
        if shard_id == "shard-a":
            return lambda: session_a
        return lambda: session_b

    mock_pool_manager.shard_session_factory.side_effect = _factory

    def _build_query(session):
        return shard_a if session is session_a else shard_b

    total, rows = fetch_evaluation_row_pairs_page(
        MagicMock(),
        _build_query,
        page=1,
        page_size=2,
        sort_key=lambda pair: pair[0].status or "",
        bounded_shard_fetch=False,
    )

    assert total == 4
    assert len(rows) == 2
    shard_a.limit.assert_not_called()
    shard_b.limit.assert_not_called()
    assert [pair[0].status for pair in rows] == ["completed", "completed"]


@patch("app.db_sharding.eval_rows.is_sharding_enabled", return_value=True)
@patch("app.db_sharding.eval_rows.scatter_gather_eval_query_count", return_value=4)
@patch("app.db_sharding.eval_rows.db_pool_manager")
def test_fetch_page_bounded_sort_limits_each_shard(
    mock_pool_manager,
    _mock_count,
    _mock_sharding,
):
    shard_a = MagicMock()
    shard_a.all.return_value = [_pair(0), _pair(1)]
    shard_a.limit.return_value = shard_a

    mock_pool_manager.router.shard_ids = ["shard-a"]
    session = MagicMock()
    mock_pool_manager.shard_session_factory.side_effect = lambda _shard_id: (
        lambda: session
    )

    total, rows = fetch_evaluation_row_pairs_page(
        MagicMock(),
        lambda _session: shard_a,
        page=1,
        page_size=2,
        sort_key=lambda pair: int(pair[1].row_index or 0),
        bounded_shard_fetch=True,
    )

    assert total == 4
    assert len(rows) == 2
    shard_a.limit.assert_called_once_with(2)
