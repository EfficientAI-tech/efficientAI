"""Unit tests for the unified call-import eval dispatch pipeline."""

from types import SimpleNamespace
from uuid import uuid4

from app.models.enums import CallImportRowStatus
from app.workers.concurrency.eval_dispatch import (
    _needs_import_for_eval,
    _needs_transcribe_for_eval,
    _try_dispatch_single_row,
)


def _evaluation(**kwargs):
    defaults = dict(
        id=uuid4(),
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
    defaults = dict(
        id=uuid4(),
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
    evaluation = _evaluation()
    eval_row = SimpleNamespace(id=uuid4(), celery_task_id=None, status="pending")
    source_row = _source_row()
    captured = {}

    class _AsyncResult:
        id = "import-task-123"

    monkeypatch.setattr(
        "app.workers.tasks.process_call_import_row.process_call_import_row_task",
        SimpleNamespace(
            apply_async=lambda *a, **kw: (
                captured.update({"apply_async_kwargs": kw}) or _AsyncResult()
            ),
        ),
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
    )

    assert result == "dispatched"
    assert captured["apply_async_kwargs"]["kwargs"]["run_eval_row_id"] == str(
        eval_row.id
    )
    assert captured["apply_async_kwargs"]["queue"] == "imports"
