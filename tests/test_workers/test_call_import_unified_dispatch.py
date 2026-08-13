"""Unit tests for the unified call-import eval dispatch pipeline."""

import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.models.enums import CallImportRowStatus
from app.workers.concurrency.eval_dispatch import (
    EvalDispatchOutcome,
    _needs_import_for_eval,
    _needs_transcribe_for_eval,
    _try_dispatch_single_row,
    build_eval_chain_import_apply_async,
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


@patch("app.workers.tasks.process_call_import_row.process_call_import_row_task")
def test_build_eval_chain_import_apply_async_passes_run_eval_row_id(mock_task):
    source_row = _source_row()
    eval_row = SimpleNamespace(id=uuid4())
    reserved_task_id = "reserved-import-task"

    async_result = MagicMock()
    async_result.id = reserved_task_id
    mock_task.apply_async.return_value = async_result

    result = build_eval_chain_import_apply_async(
        source_row=source_row,
        eval_row=eval_row,
        reserved_task_id=reserved_task_id,
    )

    assert result is async_result
    mock_task.apply_async.assert_called_once_with(
        args=(str(source_row.id),),
        kwargs={
            "_eval_slot_task_id": reserved_task_id,
            "run_eval_row_id": str(eval_row.id),
        },
        queue="imports",
        task_id=reserved_task_id,
    )


@patch("app.workers.concurrency.eval_dispatch.build_eval_chain_import_apply_async")
def test_try_dispatch_enqueues_import_for_pending_row(
    mock_build_import_apply_async, monkeypatch
):
    monkeypatch.setattr(
        "app.db_sharding.sessions.is_sharding_enabled",
        lambda: False,
    )
    monkeypatch.setattr(
        "app.services.call_imports.evaluation_bulk_op.get_evaluation_bulk_operation",
        lambda _evaluation_id: None,
    )
    monkeypatch.setattr(
        "app.workers.concurrency.import_dispatch._peek_authenticated_import_credit",
        lambda **kwargs: None,
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

    async_result = MagicMock()
    async_result.id = "import-task-123"
    mock_build_import_apply_async.return_value = async_result

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
    mock_build_import_apply_async.assert_called_once_with(
        source_row=source_row,
        eval_row=eval_row,
        reserved_task_id="reserved-id",
    )


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
