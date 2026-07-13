"""Tests for nested diarization fair dispatch within a workspace."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.workers.concurrency import fair_diarization_dispatch as fair_diarization_module
from app.workers.concurrency import diarization_dispatch as diarization_dispatch_module


@pytest.fixture(autouse=True)
def _reset_call_import_workspace_cursor(monkeypatch):
    cursors: dict[str, int] = {}

    def _get(workspace_id):
        return cursors.get(str(workspace_id), 0)

    def _set(workspace_id, cursor):
        cursors[str(workspace_id)] = cursor

    monkeypatch.setattr(
        fair_diarization_module,
        "_get_workspace_call_import_rr_cursor",
        _get,
    )
    monkeypatch.setattr(
        fair_diarization_module,
        "_set_workspace_call_import_rr_cursor",
        lambda workspace_id, cursor: _set(workspace_id, cursor),
    )


def test_dispatch_batch_interleaves_call_imports_in_same_workspace():
    workspace_id = uuid4()
    import_a = uuid4()
    import_b = uuid4()

    row_a1 = SimpleNamespace(
        id=uuid4(),
        diarised_transcript_status="pending",
        celery_task_id=None,
    )
    row_b1 = SimpleNamespace(
        id=uuid4(),
        diarised_transcript_status="pending",
        celery_task_id=None,
    )
    row_a2 = SimpleNamespace(
        id=uuid4(),
        diarised_transcript_status="pending",
        celery_task_id=None,
    )
    row_b2 = SimpleNamespace(
        id=uuid4(),
        diarised_transcript_status="pending",
        celery_task_id=None,
    )

    call_import_a = SimpleNamespace(
        id=import_a,
        workspace_id=workspace_id,
        organization_id=uuid4(),
    )
    call_import_b = SimpleNamespace(
        id=import_b,
        workspace_id=workspace_id,
        organization_id=uuid4(),
    )

    pending_by_import = {
        import_a: [(row_a1, call_import_a), (row_a2, call_import_a)],
        import_b: [(row_b1, call_import_b), (row_b2, call_import_b)],
    }
    dispatch_order: list[uuid4] = []

    def _pending_row_for_call_import(_db, call_import_id):
        rows = pending_by_import.get(call_import_id, [])
        return rows[0] if rows else None

    def _try_dispatch_single_diarization_row(**kwargs):
        call_import = kwargs["call_import"]
        row = kwargs["row"]
        dispatch_order.append(call_import.id)
        pending_by_import[call_import.id] = [
            item for item in pending_by_import[call_import.id] if item[0].id != row.id
        ]
        return "dispatched"

    db = MagicMock()
    with patch.object(
        fair_diarization_module,
        "_call_imports_with_pending_diarization",
        return_value=[import_a, import_b],
    ), patch.object(
        fair_diarization_module,
        "_pending_row_for_call_import",
        side_effect=_pending_row_for_call_import,
    ), patch.object(
        fair_diarization_module,
        "get_row_diarization_params",
        return_value={"mode": "stt_llm"},
    ), patch.object(
        fair_diarization_module,
        "pop_row_diarization_params",
    ), patch.object(
        fair_diarization_module,
        "_try_dispatch_single_diarization_row",
        side_effect=_try_dispatch_single_diarization_row,
    ):
        dispatched = fair_diarization_module._dispatch_batch_for_workspace(
            db,
            workspace_id,
            batch_size=4,
        )

    assert dispatched == 4
    assert dispatch_order == [import_a, import_b, import_a, import_b]


def test_try_dispatch_single_diarization_row_acquires_slot_before_apply_async(
    monkeypatch,
):
    row = SimpleNamespace(
        id=uuid4(),
        diarised_transcript_status="pending",
        celery_task_id=None,
    )
    call_import = SimpleNamespace(
        workspace_id=uuid4(),
        organization_id=uuid4(),
    )
    params = {"mode": "stt_llm", "overwrite_existing": False}
    db = MagicMock()

    acquire_calls: list[str] = []
    apply_async_calls: list[object] = []

    def _acquire(**kwargs):
        acquire_calls.append(kwargs["celery_task_id"])
        return True

    class _AsyncResult:
        id = "task-123"

    def _apply_async(**kwargs):
        apply_async_calls.append(kwargs)
        return _AsyncResult()

    monkeypatch.setattr(
        diarization_dispatch_module,
        "acquire_eval_slot",
        _acquire,
    )
    monkeypatch.setattr(
        "app.workers.tasks.transcribe_call_import_row.transcribe_call_import_row_task.apply_async",
        _apply_async,
    )

    result = diarization_dispatch_module._try_dispatch_single_diarization_row(
        db=db,
        row=row,
        call_import=call_import,
        params=params,
    )

    assert result == "dispatched"
    assert len(acquire_calls) == 1
    assert len(apply_async_calls) == 1
    assert apply_async_calls[0]["kwargs"]["_eval_slot_task_id"] == acquire_calls[0]
    assert row.celery_task_id == "task-123"
    db.commit.assert_called_once()
