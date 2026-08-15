"""Tests for cron job dispatch helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.models.enums import CronJobStatus
from app.services.cron.job_dispatch import advance_cron_job, enqueue_cron_job


def test_advance_cron_job_marks_completed_when_max_runs_reached():
    job = MagicMock()
    job.current_runs = 9
    job.max_runs = 10
    job.status = CronJobStatus.ACTIVE.value
    job.cron_expression = "0 * * * *"
    job.timezone = "UTC"

    advance_cron_job(MagicMock(), job, now=datetime.now(timezone.utc))

    assert job.current_runs == 10
    assert job.status == CronJobStatus.COMPLETED.value
    assert job.next_run_at is None


def test_enqueue_usage_flush_routes_to_usage_task(monkeypatch):
    job = MagicMock()
    job.job_type = "usage_flush"
    job.id = uuid4()

    delayed = MagicMock()
    delayed.id = "task-123"
    task = MagicMock()
    task.delay.return_value = delayed
    monkeypatch.setattr(
        "app.workers.tasks.flush_usage_counters.flush_usage_counters_task",
        task,
    )

    meta = enqueue_cron_job(job)

    assert meta["task"] == "flush_usage_counters"
    assert meta["celery_task_id"] == "task-123"
    task.delay.assert_called_once_with()
