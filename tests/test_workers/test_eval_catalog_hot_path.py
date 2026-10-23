"""Catalogue reads on the evaluation hot path stay narrow and cached."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

from app.workers.catalog_cache import clear_worker_catalog_cache
from app.workers.tasks.evaluate_call_import_row_core import (
    _EVALUATION_WORKER_COLUMNS,
    load_enabled_metrics,
    rollup_parent,
)


def test_worker_evaluation_columns_omit_cached_json():
    names = {column.key for column in _EVALUATION_WORKER_COLUMNS}
    assert "tldr_summary" not in names
    assert "user_insights" not in names
    assert "metric_clusters" not in names
    assert "id" in names
    assert "selected_metric_ids" in names


def test_rollup_hot_path_updates_counters_without_refresh(monkeypatch):
    evaluation = MagicMock()
    evaluation.id = uuid4()
    evaluation.total_rows = 10
    evaluation.completed_rows = 1
    evaluation.failed_rows = 0
    evaluation.status = "running"
    evaluation.started_at = datetime.now(timezone.utc)
    evaluation.billed_completed_rows = 0

    db = MagicMock()
    db.get_bind.return_value.dialect.name = "postgresql"
    db.execute.return_value.one.return_value = (2, 0)
    monkeypatch.setattr(
        "app.services.call_imports.progress_counters.clear_eval_progress_redis",
        lambda _evaluation_id: None,
    )
    monkeypatch.setattr(
        "app.workers.tasks.evaluate_call_import_row_core._should_confirm_eval_finished",
        lambda *_args, **_kwargs: False,
    )

    rollup_parent(
        db,
        evaluation,
        previous_row_status="running",
        new_row_status="completed",
    )

    db.refresh.assert_not_called()
    assert evaluation.completed_rows == 2
    assert evaluation.failed_rows == 0


def test_load_enabled_metrics_hits_the_database_once_per_process():
    clear_worker_catalog_cache()
    organization_id = uuid4()
    metric_id = uuid4()
    evaluation = MagicMock()
    evaluation.organization_id = organization_id
    evaluation.selected_metric_ids = [str(metric_id)]
    metric = MagicMock()
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [metric]

    first = load_enabled_metrics(db, evaluation)
    second = load_enabled_metrics(db, evaluation)

    assert first == [metric]
    assert second == [metric]
    assert db.query.call_count == 1
    clear_worker_catalog_cache()
