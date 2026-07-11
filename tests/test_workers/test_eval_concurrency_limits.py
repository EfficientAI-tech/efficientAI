"""Tests for Redis-backed eval concurrency limits."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.workers.concurrency import limits as limits_module


def test_acquire_eval_slot_returns_false_when_lua_returns_zero():
    client = MagicMock()
    client.eval.return_value = 0
    with patch.object(limits_module, "_get_redis", return_value=client):
        acquired = limits_module.acquire_eval_slot(
            workspace_id=uuid4(),
            organization_id=uuid4(),
            celery_task_id="task-1",
        )
    assert acquired is False


def test_acquire_eval_slot_returns_true_when_lua_returns_one():
    client = MagicMock()
    client.eval.return_value = 1
    with patch.object(limits_module, "_get_redis", return_value=client):
        acquired = limits_module.acquire_eval_slot(
            workspace_id=uuid4(),
            organization_id=uuid4(),
            celery_task_id="task-2",
        )
    assert acquired is True


def test_release_eval_slot_for_celery_task_noops_when_task_unregistered():
    client = MagicMock()
    client.hgetall.return_value = {}
    with patch.object(limits_module, "_get_redis", return_value=client):
        limits_module.release_eval_slot_for_celery_task("missing-task")
    client.eval.assert_not_called()


def test_release_eval_slot_for_celery_task_decrements_counters():
    client = MagicMock()
    client.hgetall.return_value = {
        "workspace_id": str(uuid4()),
        "organization_id": str(uuid4()),
    }
    with patch.object(limits_module, "_get_redis", return_value=client):
        limits_module.release_eval_slot_for_celery_task("task-3")
    client.eval.assert_called_once()
