"""Unit tests for the unified call-import eval dispatch pipeline."""

import importlib
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.enums import CallImportRowStatus
from app.workers.concurrency.eval_dispatch import (
    EvalDispatchOutcome,
    _needs_import_for_eval,
    _needs_transcribe_for_eval,
    _try_dispatch_single_row,
)


def _import_task_module():
    """Load process_call_import_row with the test Celery wrapper."""
    from tests.test_workers.test_process_call_import_row import _load_task_module

    return _load_task_module()


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


def test_needs_import_skipped_for_production_source():
    """Production transcript runs skip recording import even when a URL exists."""
    row = _source_row()
    evaluation = _evaluation(transcript_source="production")
    assert _needs_import_for_eval(row, evaluation) is False


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
    captured = {}

    class _AsyncResult:
        id = "import-task-123"

    import_mod = _import_task_module()
    fake_import_task = SimpleNamespace(
        apply_async=lambda *a, **kw: captured.update({"apply_async_kwargs": kw})
        or _AsyncResult(),
    )
    monkeypatch.setattr(import_mod, "process_call_import_row_task", fake_import_task)

    def fake_reserve(**kwargs):
        kwargs["enqueue_fn"]("reserved-id")
        return True

    monkeypatch.setattr(
        "app.workers.concurrency.eval_dispatch._reserve_slot_and_enqueue",
        fake_reserve,
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


def test_try_dispatch_skips_import_for_production_transcript(monkeypatch):
    monkeypatch.setattr(
        "app.db_sharding.sessions.is_sharding_enabled",
        lambda: False,
    )
    evaluation = _evaluation(transcript_source="production")
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
        transcript="Agent: hello",
    )
    import_called = {"value": False}
    eval_called = {"value": False}

    class _AsyncResult:
        id = "eval-task-123"

    import_mod = _import_task_module()
    fake_import_task = SimpleNamespace(
        apply_async=lambda *a, **kw: import_called.update({"value": True})
        or _AsyncResult(),
    )
    monkeypatch.setattr(import_mod, "process_call_import_row_task", fake_import_task)
    eval_mod = importlib.import_module("app.workers.tasks.evaluate_call_import_row")
    fake_eval_task = SimpleNamespace(
        apply_async=lambda *a, **kw: eval_called.update({"value": True})
        or _AsyncResult(),
    )
    monkeypatch.setattr(eval_mod, "evaluate_call_import_row_task", fake_eval_task)
    monkeypatch.setattr(
        "app.workers.tasks.evaluate_call_import_row_core.row_needs_audio_phase",
        lambda *_a, **_kw: False,
    )

    def fake_reserve(**kwargs):
        kwargs["enqueue_fn"]("reserved-id")
        return True

    monkeypatch.setattr(
        "app.workers.concurrency.eval_dispatch._reserve_slot_and_enqueue",
        fake_reserve,
    )

    result = _try_dispatch_single_row(
        db=SimpleNamespace(commit=lambda: None, flush=lambda: None),
        evaluation=evaluation,
        eval_row=eval_row,
        source_row=source_row,
        call_import=call_import,
    )

    assert result == EvalDispatchOutcome("dispatched")
    assert import_called["value"] is False
    assert eval_called["value"] is True
