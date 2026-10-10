"""Tests for platform historical call import helpers."""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.services.call_imports.debounced_rollup import platform_discovery_blocks_terminal_status
from app.services.call_imports.platform_discovery import platform_row_id, plan_time_slices
from app.services.voice_providers.historical.base import (
    build_canonical_recording_url,
    parse_canonical_recording_url,
)


def test_build_and_parse_canonical_recording_url():
    url = build_canonical_recording_url("elevenlabs", "conv-123")
    assert url == "elevenlabs://conversations/conv-123"
    provider, conv_id = parse_canonical_recording_url(url)
    assert provider == "elevenlabs"
    assert conv_id == "conv-123"


def test_platform_row_id_is_deterministic():
    import_id = uuid4()
    a = platform_row_id(import_id, "abc")
    b = platform_row_id(import_id, "abc")
    c = platform_row_id(import_id, "xyz")
    assert a == b
    assert a != c


def test_plan_time_slices_splits_by_day_and_agent():
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = datetime(2025, 1, 3, tzinfo=timezone.utc)
    slices = plan_time_slices(start, end, ["agent-a", "agent-b"])
    assert len(slices) == 4


def test_reclaim_stale_platform_import_dispatches_clears_task_id(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from unittest.mock import MagicMock

    from app.models.enums import CallImportRowStatus
    from app.workers.concurrency.platform_import_dispatch import (
        reclaim_stale_platform_import_dispatches,
    )

    released: list[str] = []
    monkeypatch.setattr(
        "app.workers.concurrency.platform_import_dispatch.release_platform_import_slot",
        lambda tid: released.append(tid),
    )

    row = MagicMock()
    row.celery_task_id = "task-stale"
    row.attempts = 0
    row.updated_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    row.status = CallImportRowStatus.PENDING

    db = MagicMock()
    db.query.return_value.join.return_value.filter.return_value.limit.return_value.all.return_value = [
        row
    ]

    count = reclaim_stale_platform_import_dispatches(db)
    assert count == 1
    assert row.celery_task_id is None
    assert released == ["task-stale"]
    db.commit.assert_called_once()


def test_discovery_blocks_terminal_status_while_running():
    batch = SimpleNamespace(source_format="platform", discovery_status="running")
    assert platform_discovery_blocks_terminal_status(batch) is True
    batch.discovery_status = "completed"
    assert platform_discovery_blocks_terminal_status(batch) is False
