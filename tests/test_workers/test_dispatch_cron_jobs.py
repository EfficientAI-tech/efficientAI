"""Tests for evaluator cron dispatcher task (Beat-driven, no self-scheduling)."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.workers.tasks.dispatch_cron_jobs import dispatch_cron_jobs_task


def test_locked_tick_does_not_reschedule(monkeypatch):
    monkeypatch.setattr(
        "app.services.cron.dispatcher_lock.refresh_dispatcher_leader",
        lambda: None,
    )
    monkeypatch.setattr(
        "app.services.cron.dispatcher_lock.acquire_dispatcher_run_lock",
        lambda: False,
    )
    apply_async = MagicMock()
    monkeypatch.setattr(dispatch_cron_jobs_task, "apply_async", apply_async)

    result = dispatch_cron_jobs_task.run()

    assert result == {"skipped": "locked"}
    apply_async.assert_not_called()


def test_successful_tick_does_not_reschedule(monkeypatch):
    monkeypatch.setattr(
        "app.services.cron.dispatcher_lock.refresh_dispatcher_leader",
        lambda: None,
    )
    monkeypatch.setattr(
        "app.services.cron.dispatcher_lock.acquire_dispatcher_run_lock",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.cron.dispatcher_lock.release_dispatcher_run_lock",
        lambda: None,
    )
    monkeypatch.setattr(
        "app.services.cron.job_dispatch.list_due_cron_jobs",
        lambda db: [],
    )
    db = MagicMock()
    monkeypatch.setattr(
        "app.workers.tasks.dispatch_cron_jobs.SessionLocal",
        lambda: db,
    )
    apply_async = MagicMock()
    monkeypatch.setattr(dispatch_cron_jobs_task, "apply_async", apply_async)

    result = dispatch_cron_jobs_task.run()

    assert result == {"dispatched": 0, "jobs": []}
    apply_async.assert_not_called()
    db.close.assert_called_once()
