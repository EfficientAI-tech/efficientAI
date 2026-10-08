"""Cron job alert metrics."""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.services.alerts.cron_metrics import compute_cron_jobs_metric


def test_compute_cron_jobs_failure_count_dispatch_failed():
    org_id = uuid4()
    job_failed = SimpleNamespace(
        last_dispatch_status="failed",
        last_run_status=None,
        last_run_at=None,
        updated_at=datetime.now(timezone.utc),
    )
    job_ok = SimpleNamespace(
        last_dispatch_status="enqueued",
        last_run_status="success",
        last_run_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    class FakeQuery:
        def filter(self, *_a, **_k):
            return self

        def all(self):
            return [job_failed, job_ok]

    class FakeDb:
        def query(self, _model):
            return FakeQuery()

    window_start = datetime.now(timezone.utc)
    value = compute_cron_jobs_metric(
        FakeDb(), org_id, "failure_count", window_start
    )
    assert value == 1.0
