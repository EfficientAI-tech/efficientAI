"""Tests for fair diarization dispatch param storage and failure handling."""

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
import redis

from app.workers.concurrency.diarization_dispatch import (
    _MISSING_PARAMS_ERROR,
    _REDIS_PARAMS_STORE_ERROR,
    store_row_diarization_params,
)
from app.workers.concurrency.fair_diarization_dispatch import (
    _dispatch_batch_for_workspace,
)


def test_store_row_diarization_params_returns_false_on_redis_error(monkeypatch):
    fake_redis = MagicMock()
    fake_redis.setex.side_effect = redis.RedisError("connection refused")
    monkeypatch.setattr(
        "app.workers.concurrency.diarization_dispatch._get_redis",
        lambda: fake_redis,
    )

    ok = store_row_diarization_params(uuid4(), {"mode": "stt_llm"})

    assert ok is False


def test_dispatch_batch_marks_row_failed_when_params_missing(monkeypatch):
    row_id = uuid4()
    row = SimpleNamespace(
        id=row_id,
        diarised_transcript_status="pending",
        diarised_transcript_error=None,
        celery_task_id=None,
        created_at=0,
    )
    call_import = SimpleNamespace(
        id=uuid4(),
        workspace_id=uuid4(),
        organization_id=uuid4(),
    )
    fake_db = MagicMock()

    monkeypatch.setattr(
        "app.workers.concurrency.fair_diarization_dispatch._call_imports_with_pending_diarization",
        lambda _db, _ws: [call_import.id],
    )
    monkeypatch.setattr(
        "app.workers.concurrency.fair_diarization_dispatch._pending_row_for_call_import",
        lambda _db, _cid: (row, call_import),
    )
    monkeypatch.setattr(
        "app.workers.concurrency.fair_diarization_dispatch.get_row_diarization_params",
        lambda _row_id: None,
    )
    monkeypatch.setattr(
        "app.workers.concurrency.fair_diarization_dispatch._get_workspace_call_import_rr_cursor",
        lambda _ws: 0,
    )
    monkeypatch.setattr(
        "app.workers.concurrency.fair_diarization_dispatch._set_workspace_call_import_rr_cursor",
        lambda *_args, **_kwargs: None,
    )

    dispatched = _dispatch_batch_for_workspace(
        fake_db,
        call_import.workspace_id,
        batch_size=1,
    )

    assert dispatched == 0
    assert row.diarised_transcript_status == "failed"
    assert row.diarised_transcript_error == _MISSING_PARAMS_ERROR
    fake_db.commit.assert_called()


def test_redis_store_error_message_is_actionable():
    assert "Redis" in _REDIS_PARAMS_STORE_ERROR
