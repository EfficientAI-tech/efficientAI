"""Tests for eval-chain vs standalone transcribe queue routing."""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.models.enums import CallImportRowStatus
from app.workers.concurrency.diarization_dispatch import (
    _try_dispatch_single_diarization_row,
)
from app.workers.concurrency.eval_dispatch import (
    DIARIZATION_QUEUE,
    EvalDispatchOutcome,
    _try_dispatch_single_row,
)


@pytest.fixture(autouse=True)
def stub_worker_task_modules():
    """Avoid importing heavy worker task package __init__ (optional deps)."""
    mock_transcribe_task = MagicMock()

    fake_tasks_pkg = types.ModuleType("app.workers.tasks")
    fake_tasks_pkg.__path__ = []

    fake_transcribe = types.ModuleType("app.workers.tasks.transcribe_call_import_row")
    fake_transcribe.transcribe_call_import_row_task = mock_transcribe_task

    fake_eval = types.ModuleType("app.workers.tasks.evaluate_call_import_row")
    fake_eval.evaluate_call_import_row_task = MagicMock()

    fake_audio = types.ModuleType("app.workers.tasks.evaluate_call_import_row_audio")
    fake_audio.evaluate_call_import_row_audio_task = MagicMock()

    fake_core = types.ModuleType("app.workers.tasks.evaluate_call_import_row_core")
    fake_core.row_needs_audio_phase = lambda *_a, **_kw: False

    fake_process_import = types.ModuleType("app.workers.tasks.process_call_import_row")
    fake_process_import.process_call_import_row_task = MagicMock()

    modules = {
        "app.workers.tasks": fake_tasks_pkg,
        "app.workers.tasks.transcribe_call_import_row": fake_transcribe,
        "app.workers.tasks.evaluate_call_import_row": fake_eval,
        "app.workers.tasks.evaluate_call_import_row_audio": fake_audio,
        "app.workers.tasks.evaluate_call_import_row_core": fake_core,
        "app.workers.tasks.process_call_import_row": fake_process_import,
    }
    previous = {key: sys.modules.get(key) for key in modules}
    sys.modules.update(modules)
    try:
        yield mock_transcribe_task
    finally:
        for key, value in previous.items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value


def _fake_async_result(task_id: str):
    result = MagicMock()
    result.id = task_id
    return result


@patch(
    "app.workers.concurrency.eval_dispatch.acquire_eval_slot",
    return_value=True,
)
def test_eval_chain_transcribe_uses_diarization_queue(
    _mock_acquire,
    stub_worker_task_modules,
    monkeypatch,
):
    monkeypatch.setattr(
        "app.db_sharding.sessions.is_sharding_enabled",
        lambda: False,
    )
    stub_worker_task_modules.apply_async.side_effect = (
        lambda **kwargs: _fake_async_result(kwargs["task_id"])
    )

    eval_row_id = uuid4()
    source_row_id = uuid4()
    evaluation = SimpleNamespace(
        id=uuid4(),
        call_import_id=uuid4(),
        workspace_id=uuid4(),
        organization_id=uuid4(),
        status="pending",
        transcribe_mode="stt_llm",
        stt_provider="openai",
        stt_model="whisper-1",
        stt_credential_id=uuid4(),
        diarisation_llm_provider="openai",
        diarisation_llm_model="gpt-4o",
        diarisation_llm_credential_id=uuid4(),
        diarisation_prompt=None,
    )
    eval_row = SimpleNamespace(id=eval_row_id, celery_task_id=None)
    source_row = SimpleNamespace(
        id=source_row_id,
        call_import_id=evaluation.call_import_id,
        row_index=0,
        status=CallImportRowStatus.COMPLETED,
        recording_s3_key="audio/test.wav",
        diarised_transcript="",
        diarised_transcript_status=None,
        celery_task_id=None,
    )
    db = MagicMock()

    result = _try_dispatch_single_row(
        db=db,
        evaluation=evaluation,
        eval_row=eval_row,
        source_row=source_row,
    )

    assert result == EvalDispatchOutcome("dispatched")
    stub_worker_task_modules.apply_async.assert_called_once()
    call_kwargs = stub_worker_task_modules.apply_async.call_args.kwargs
    assert call_kwargs["queue"] == DIARIZATION_QUEUE
    assert call_kwargs["args"][6] == str(eval_row_id)


@patch(
    "app.workers.concurrency.eval_dispatch.acquire_eval_slot",
    return_value=True,
)
def test_eval_dispatch_skips_failed_diarization_without_overwrite(
    _mock_acquire,
    stub_worker_task_modules,
):
    evaluation = SimpleNamespace(
        id=uuid4(),
        call_import_id=uuid4(),
        workspace_id=uuid4(),
        organization_id=uuid4(),
        status="pending",
        transcribe_mode="stt_llm",
        stt_provider="openai",
        stt_model="whisper-1",
        stt_credential_id=uuid4(),
        diarisation_llm_provider="openai",
        diarisation_llm_model="gpt-4o",
        diarisation_llm_credential_id=uuid4(),
        diarisation_prompt=None,
    )
    eval_row = SimpleNamespace(id=uuid4(), celery_task_id=None)
    source_row = SimpleNamespace(
        id=uuid4(),
        call_import_id=evaluation.call_import_id,
        row_index=0,
        status=CallImportRowStatus.COMPLETED,
        recording_s3_key="audio/test.wav",
        diarised_transcript="",
        diarised_transcript_status="failed",
        diarised_transcript_error="Diariser returned no storable transcript text.",
        celery_task_id=None,
    )
    db = MagicMock()

    result = _try_dispatch_single_row(
        db=db,
        evaluation=evaluation,
        eval_row=eval_row,
        source_row=source_row,
        transcribe_overwrite=False,
    )

    assert result == EvalDispatchOutcome("skip")
    stub_worker_task_modules.apply_async.assert_not_called()


@patch(
    "app.workers.concurrency.diarization_dispatch.acquire_eval_slot",
    return_value=True,
)
def test_standalone_diarization_uses_diarization_queue(
    _mock_acquire,
    stub_worker_task_modules,
):
    stub_worker_task_modules.apply_async.side_effect = (
        lambda **kwargs: _fake_async_result(kwargs["task_id"])
    )

    row_id = uuid4()
    row = SimpleNamespace(
        id=row_id,
        diarised_transcript_status="pending",
        celery_task_id=None,
    )
    call_import = SimpleNamespace(
        workspace_id=uuid4(),
        organization_id=uuid4(),
    )
    params = {
        "stt_provider": "openai",
        "stt_model": "whisper-1",
        "credential_id": None,
        "language": None,
        "overwrite_existing": False,
        "diarization_llm_provider": "openai",
        "diarization_llm_model": "gpt-4o",
        "diarization_llm_credential_id": None,
        "diarization_prompt": None,
        "mode": "stt_llm",
    }
    db = MagicMock()

    result = _try_dispatch_single_diarization_row(
        db=db,
        row=row,
        call_import=call_import,
        params=params,
    )

    assert result == "dispatched"
    stub_worker_task_modules.apply_async.assert_called_once()
    call_kwargs = stub_worker_task_modules.apply_async.call_args.kwargs
    assert call_kwargs["queue"] == DIARIZATION_QUEUE
    assert call_kwargs["args"][6] is None
