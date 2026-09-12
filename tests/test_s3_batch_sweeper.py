"""Tests for orphan S3 batch sweeper idempotency."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

from app.services.synthetic_traces.s3_batch_sweeper import sweep_orphan_s3_batches


def test_sweep_orphan_s3_batches_skips_processed(monkeypatch):
    org = uuid4()
    ws = uuid4()
    trace = uuid4()
    key = f"traces/organizations/{org}/workspaces/{ws}/traces/{trace}/batches/1.json"

    monkeypatch.setattr(
        "app.services.synthetic_traces.s3_batch_sweeper.clickhouse_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.synthetic_traces.s3_batch_sweeper.settings.S3_ENABLED",
        True,
    )
    monkeypatch.setattr(
        "app.services.synthetic_traces.s3_batch_sweeper.is_batch_processed",
        lambda _key: True,
    )
    monkeypatch.setattr(
        "app.services.synthetic_traces.s3_batch_sweeper.blob_storage_service.list_objects_with_prefix",
        lambda *_args, **_kwargs: [(key, datetime.now(timezone.utc))],
    )
    scheduled = {"called": False}

    def _schedule(**_kwargs):
        scheduled["called"] = True

    monkeypatch.setattr(
        "app.services.synthetic_traces.ingest_pipeline.schedule_s3_batch_process",
        _schedule,
    )

    requeued = sweep_orphan_s3_batches()

    assert requeued == 0
    assert scheduled["called"] is False
