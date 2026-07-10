"""Tests for workspace round-robin fair eval dispatch."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.workers.concurrency import fair_dispatch as fair_dispatch_module


def test_get_and_set_rr_cursor():
    client = MagicMock()
    client.get.return_value = "3"
    with patch.object(fair_dispatch_module, "_get_redis", return_value=client):
        assert fair_dispatch_module._get_rr_cursor() == 3
        fair_dispatch_module._set_rr_cursor(5)
    client.set.assert_called_once_with(fair_dispatch_module._RR_CURSOR_KEY, "5")


def test_schedule_fair_dispatch_enqueues_task():
    with patch.object(
        fair_dispatch_module.dispatch_fair_eval_rows_task,
        "apply_async",
    ) as mock_apply:
        fair_dispatch_module.schedule_fair_dispatch(max_workspace_turns=1)
    mock_apply.assert_called_once()
    assert mock_apply.call_args.kwargs["kwargs"]["max_workspace_turns"] == 1


def test_store_and_pop_row_restricted_metrics():
    client = MagicMock()
    client.get.return_value = '["metric-a", "metric-b"]'
    row_id = uuid4()
    with patch.object(fair_dispatch_module, "_get_redis", return_value=client):
        fair_dispatch_module.store_row_restricted_metrics(
            row_id,
            ["metric-a", "metric-b"],
        )
        result = fair_dispatch_module.pop_row_restricted_metrics(row_id)
    assert result == ["metric-a", "metric-b"]
    client.delete.assert_called_once()
