"""Unit tests for the unified call-import eval dispatch pipeline."""

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.models.enums import CallImportRowStatus
from app.workers.concurrency.eval_dispatch import (
    EvalDispatchOutcome,
    _needs_import_for_eval,
    _needs_transcribe_for_eval,
    _try_dispatch_single_row,
)


def _evaluation(**kwargs):
    defaults = dict(
        id=uuid4(),
        call_import_id=uuid4(),
        status="running",
        workspace_id=uuid4(),
        organization_id=uuid4(),
        stt_provider="openai",
        stt_model="whisper-1",
        stt_credential_id=None,
        diarisation_llm_provider="openai",
        diarisation_llm_model="gpt-4o-mini",
        diarisation_llm_credential_id=None,
        diarisation_prompt=None,
        transcribe_mode="stt_llm",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _source_row(**kwargs):
    call_import_id = kwargs.pop("call_import_id", None)
    if call_import_id is None:
        call_import = kwargs.pop("call_import", None)
        if call_import is not None:
            call_import_id = call_import.id
    defaults = dict(
        id=uuid4(),
        call_import_id=call_import_id or uuid4(),
        row_index=0,
        recording_s3_key=None,
        recording_url="https://example.com/rec.mp3",
        status=CallImportRowStatus.PENDING,
        diarised_transcript=None,
        diarised_transcript_status=None,
        celery_task_id=None,
        error_message=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_needs_import_for_eval_when_pending_with_url():
    row = _source_row()
    assert _needs_import_for_eval(row) is True


def test_needs_import_false_when_completed():
    row = _source_row(
        status=CallImportRowStatus.COMPLETED,
        recording_s3_key="orgs/x/call_imports/y/z.mp3",
    )
    assert _needs_import_for_eval(row) is False


def test_needs_import_false_when_failed():
    row = _source_row(status=CallImportRowStatus.FAILED)
    assert _needs_import_for_eval(row) is False


def test_needs_import_for_production_source_still_fetches_recording():
    """Production transcript runs skip diarisation but still import recordings
    when a recording_url is present (same as diarised runs)."""
    row = _source_row()
    evaluation = _evaluation(transcript_source="production")
    assert _needs_import_for_eval(row) is True


def test_needs_transcribe_after_recording_ready():
    evaluation = _evaluation()
    row = _source_row(
        status=CallImportRowStatus.COMPLETED,
        recording_s3_key="orgs/x/call_imports/y/z.mp3",
    )
    assert (
        _needs_transcribe_for_eval(
            evaluation,
            row,
            transcribe_overwrite=False,
            auto_transcribe=True,
        )
        is True
    )


def test_try_dispatch_enqueues_import_for_pending_row(monkeypatch):
    monkeypatch.setattr(
        "app.db_sharding.sessions.is_sharding_enabled",
        lambda: False,
    )
    evaluation = _evaluation()
    eval_row = SimpleNamespace(id=uuid4(), celery_task_id=None, status="pending")
    call_import = SimpleNamespace(
        id=evaluation.call_import_id,
        organization_id=evaluation.organization_id,
        workspace_id=evaluation.workspace_id,
        provider=None,
        telephony_integration_id=None,
    )
    source_row = _source_row(
        call_import_id=evaluation.call_import_id,
    )
    captured: dict = {}

    def _fake_apply_async(*args, **kwargs):
        captured["apply_async_kwargs"] = kwargs
        result = MagicMock()
        result.id = kwargs.get("task_id", "import-task-123")
        return result

    monkeypatch.setattr(
        "app.workers.concurrency.eval_dispatch.acquire_eval_slot",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        "app.workers.tasks.process_call_import_row.process_call_import_row_task.apply_async",
        _fake_apply_async,
    )
    monkeypatch.setattr(
        "app.workers.concurrency.import_dispatch._peek_authenticated_import_credit",
        lambda **kwargs: None,
    )

    result = _try_dispatch_single_row(
        db=SimpleNamespace(commit=lambda: None, flush=lambda: None),
        evaluation=evaluation,
        eval_row=eval_row,
        source_row=source_row,
        call_import=call_import,
    )

    assert result == EvalDispatchOutcome("dispatched")
    assert captured["apply_async_kwargs"]["kwargs"]["run_eval_row_id"] == str(
        eval_row.id
    )
    assert captured["apply_async_kwargs"]["queue"] == "imports"
