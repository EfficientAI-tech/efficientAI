from unittest.mock import MagicMock

from app.services.call_imports.metric_aggregate_cache import (
    maybe_refresh_aggregate_cache_after_row,
)


def test_aggregate_cache_refresh_skipped_while_eval_running():
    evaluation = MagicMock()
    evaluation.status = "running"
    evaluation.completed_rows = 50
    evaluation.cached_metric_aggregates_at_count = 0
    db = MagicMock()

    maybe_refresh_aggregate_cache_after_row(
        db, evaluation, new_row_status="completed"
    )

    db.query.assert_not_called()


def test_aggregate_cache_refresh_when_eval_terminal(monkeypatch):
    evaluation = MagicMock()
    evaluation.status = "completed"
    evaluation.completed_rows = 50
    evaluation.cached_metric_aggregates_at_count = 40
    evaluation.id = "eval-id"
    db = MagicMock()

    rebuild = MagicMock()
    monkeypatch.setattr(
        "app.services.call_imports.metric_aggregate_cache.rebuild_evaluation_metric_aggregate_cache",
        rebuild,
    )

    maybe_refresh_aggregate_cache_after_row(
        db, evaluation, new_row_status="completed"
    )

    rebuild.assert_called_once_with(db, "eval-id")
