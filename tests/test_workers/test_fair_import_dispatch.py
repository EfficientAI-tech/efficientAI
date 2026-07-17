"""Tests for fair round-robin import dispatch."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.models.database import CallImport, CallImportRow
from app.models.enums import CallImportRowStatus, CallImportStatus
from app.workers.concurrency.import_dispatch import ImportDispatchOutcome


def _seed_pending_rows(db_session, *, workspace_count: int = 2, jobs_per_ws: int = 2):
    from app.models.database import Organization, Workspace

    org = Organization(id=uuid4(), name="Fair Import Org")
    db_session.add(org)

    workspaces = []
    for i in range(workspace_count):
        ws = Workspace(
            id=uuid4(),
            organization_id=org.id,
            name=f"WS-{i}",
            slug=f"ws-{i}",
            is_default=(i == 0),
        )
        db_session.add(ws)
        workspaces.append(ws)
    db_session.commit()

    call_imports: list[CallImport] = []
    rows: list[CallImportRow] = []
    for ws in workspaces:
        for job_idx in range(jobs_per_ws):
            call_import = CallImport(
                organization_id=org.id,
                workspace_id=ws.id,
                original_filename=f"batch-{ws.slug}-{job_idx}.csv",
                total_rows=1,
                completed_rows=0,
                failed_rows=0,
                status=CallImportStatus.PROCESSING,
            )
            db_session.add(call_import)
            db_session.flush()
            call_imports.append(call_import)

            row = CallImportRow(
                call_import_id=call_import.id,
                organization_id=org.id,
                row_index=0,
                conversation_id=f"call-{ws.slug}-{job_idx}",
                recording_url="https://example.com/rec.mp3",
                status=CallImportRowStatus.PENDING,
            )
            db_session.add(row)
            rows.append(row)
    db_session.commit()
    return org, workspaces, call_imports, rows


@patch("app.workers.concurrency.fair_import_dispatch._set_rr_cursor")
@patch("app.workers.concurrency.fair_import_dispatch._get_rr_cursor", return_value=0)
@patch("app.workers.concurrency.fair_import_dispatch._dispatch_batch_for_workspace")
def test_dispatch_fair_import_rows_advances_workspace_cursor(
    mock_dispatch_batch,
    _mock_get_cursor,
    mock_set_cursor,
    db_session,
):
    from app.workers.concurrency.fair_import_dispatch import (
        dispatch_fair_import_rows_task,
    )

    _, workspaces, _, _ = _seed_pending_rows(db_session, workspace_count=2)
    mock_dispatch_batch.side_effect = [(2, False, 0), (1, False, 0)]

    with patch(
        "app.workers.concurrency.fair_import_dispatch.SessionLocal",
        return_value=db_session,
    ):
        result = dispatch_fair_import_rows_task.run(max_workspace_turns=2)

    assert result["dispatched"] == 3
    assert result["turns_served"] == 2
    assert mock_dispatch_batch.call_count == 2
    assert mock_set_cursor.call_count == 2
    assert mock_set_cursor.call_args_list[0].args[0] == 1
    assert mock_set_cursor.call_args_list[1].args[0] == 0


@patch(
    "app.workers.concurrency.fair_import_dispatch._try_dispatch_single_import_row",
    return_value=ImportDispatchOutcome("dispatched"),
)
@patch(
    "app.workers.concurrency.fair_import_dispatch._get_workspace_call_import_rr_cursor",
    return_value=0,
)
@patch(
    "app.workers.concurrency.fair_import_dispatch._set_workspace_call_import_rr_cursor",
)
def test_dispatch_batch_interleaves_call_imports(
    mock_set_ws_cursor,
    _mock_get_ws_cursor,
    mock_try_dispatch,
    db_session,
):
    from app.workers.concurrency.fair_import_dispatch import (
        _dispatch_batch_for_workspace,
    )

    _, workspaces, call_imports, _ = _seed_pending_rows(
        db_session, workspace_count=1, jobs_per_ws=2
    )
    ws_id = workspaces[0].id
    ws_imports = [ci for ci in call_imports if ci.workspace_id == ws_id]

    dispatched, _hit_capacity, _backoff = _dispatch_batch_for_workspace(
        db_session, ws_id, batch_size=2
    )

    assert dispatched == 2
    assert mock_try_dispatch.call_count == 2
    dispatched_import_ids = [
        call.kwargs["call_import"].id for call in mock_try_dispatch.call_args_list
    ]
    expected_ids = sorted(ci.id for ci in ws_imports)
    assert dispatched_import_ids == expected_ids
    mock_set_ws_cursor.assert_called_once()


@patch(
    "app.workers.concurrency.fair_import_dispatch._try_dispatch_single_import_row",
    return_value=ImportDispatchOutcome("at_capacity"),
)
@patch(
    "app.workers.concurrency.fair_import_dispatch._get_workspace_call_import_rr_cursor",
    return_value=0,
)
@patch(
    "app.workers.concurrency.fair_import_dispatch._set_workspace_call_import_rr_cursor",
)
def test_dispatch_batch_persists_cursor_on_at_capacity(
    mock_set_ws_cursor,
    _mock_get_ws_cursor,
    _mock_try_dispatch,
    db_session,
):
    from app.workers.concurrency.fair_import_dispatch import (
        _dispatch_batch_for_workspace,
    )

    _, workspaces, _, _ = _seed_pending_rows(db_session, workspace_count=1, jobs_per_ws=1)
    ws_id = workspaces[0].id

    dispatched, _hit_capacity, _backoff = _dispatch_batch_for_workspace(
        db_session, ws_id, batch_size=5
    )

    assert dispatched == 0
    mock_set_ws_cursor.assert_called_once_with(ws_id, 0)


@patch(
    "app.workers.concurrency.fair_import_dispatch.schedule_fair_import_dispatch",
)
@patch(
    "app.workers.concurrency.limits.release_import_slot_for_celery_task",
)
def test_finish_import_work_and_redispatch(
    mock_release,
    mock_schedule,
):
    from app.workers.concurrency.fair_import_dispatch import (
        finish_import_work_and_redispatch,
    )

    finish_import_work_and_redispatch("task-123")

    mock_release.assert_called_once_with("task-123")
    mock_schedule.assert_called_once_with(max_workspace_turns=1)


@patch(
    "app.workers.concurrency.import_dispatch.release_import_slot_for_celery_task",
)
@patch(
    "app.workers.concurrency.import_dispatch.acquire_import_slot",
    return_value=True,
)
def test_try_dispatch_single_import_row_enqueues_task(
    mock_acquire,
    mock_release,
    db_session,
):
    from app.workers.concurrency.import_dispatch import (
        ImportDispatchOutcome,
        _try_dispatch_single_import_row,
    )

    _, _, call_imports, rows = _seed_pending_rows(db_session, workspace_count=1, jobs_per_ws=1)
    row = rows[0]
    call_import = call_imports[0]

    fake_task = MagicMock()
    fake_async = MagicMock()
    fake_async.id = "reserved-task-id"
    fake_task.apply_async.return_value = fake_async

    with patch(
        "app.workers.tasks.process_call_import_row.process_call_import_row_task",
        fake_task,
    ):
        result = _try_dispatch_single_import_row(
            db=db_session,
            row=row,
            call_import=call_import,
        )

    assert result == ImportDispatchOutcome("dispatched")
    mock_acquire.assert_called_once()
    fake_task.apply_async.assert_called_once()
    db_session.refresh(row)
    assert row.celery_task_id == "reserved-task-id"
    mock_release.assert_not_called()
