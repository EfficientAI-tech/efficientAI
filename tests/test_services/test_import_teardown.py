"""Unit tests for chunked call-import teardown."""

from uuid import uuid4

import pytest

from app.models.database import (
    CallImport,
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
)
from app.models.enums import CallImportStatus
from app.services.call_imports.delete_teardown_lock import clear_call_import_delete_lock
from app.services.call_imports.import_teardown import execute_call_import_delete_chunk


@pytest.fixture(autouse=True)
def stub_delete_continuation(monkeypatch):
    fake_module = __import__(
        "app.workers.tasks.call_import_bulk_ops",
        fromlist=["delete_call_import_task"],
    )

    class _Noop:
        @staticmethod
        def delay(*_a, **_kw):
            return None

    monkeypatch.setattr(fake_module, "delete_call_import_task", _Noop())


def _make_deleting_import(db_session, org_id, workspace_id, *, row_count: int):
    call_import = CallImport(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=workspace_id,
        original_filename="teardown-test.csv",
        column_mapping={},
        status=CallImportStatus.DELETING,
        total_rows=row_count,
        completed_rows=row_count,
    )
    db_session.add(call_import)
    db_session.flush()

    eval_run = CallImportEvaluation(
        id=uuid4(),
        call_import_id=call_import.id,
        organization_id=org_id,
        workspace_id=workspace_id,
        selected_metric_ids=[],
        status="completed",
        total_rows=row_count,
    )
    db_session.add(eval_run)
    db_session.flush()

    for index in range(row_count):
        row = CallImportRow(
            id=uuid4(),
            call_import_id=call_import.id,
            organization_id=org_id,
            workspace_id=workspace_id,
            row_index=index,
            conversation_id=f"conv-{index}",
            status="completed",
        )
        db_session.add(row)
        db_session.flush()
        db_session.add(
            CallImportEvaluationRow(
                id=uuid4(),
                evaluation_id=eval_run.id,
                call_import_row_id=row.id,
                workspace_id=workspace_id,
                status="completed",
                metric_scores={},
            )
        )
    db_session.commit()
    return call_import


def test_chunked_delete_finishes_in_multiple_invocations(
    db_session, org_id, default_workspace,
):
    workspace_id = default_workspace.id
    call_import = _make_deleting_import(db_session, org_id, workspace_id, row_count=3)
    clear_call_import_delete_lock(call_import.id)

    first = execute_call_import_delete_chunk(
        db_session, call_import.id, org_id,
    )
    assert first["status"] == "continuing"

    still = (
        db_session.query(CallImport)
        .filter(CallImport.id == call_import.id)
        .first()
    )
    assert still is not None
    assert still.status == CallImportStatus.DELETING

    while True:
        clear_call_import_delete_lock(call_import.id)
        result = execute_call_import_delete_chunk(
            db_session, call_import.id, org_id,
        )
        if result["status"] == "completed":
            break
        assert result["status"] in {"continuing", "skipped"}

    assert (
        db_session.query(CallImport)
        .filter(CallImport.id == call_import.id)
        .count()
        == 0
    )


def test_resume_after_partial_row_delete(
    db_session, org_id, default_workspace,
):
    workspace_id = default_workspace.id
    call_import = _make_deleting_import(db_session, org_id, workspace_id, row_count=2)
    clear_call_import_delete_lock(call_import.id)

    execute_call_import_delete_chunk(db_session, call_import.id, org_id)
    db_session.query(CallImportRow).filter(
        CallImportRow.call_import_id == call_import.id
    ).delete(synchronize_session=False)
    db_session.commit()

    clear_call_import_delete_lock(call_import.id)
    while True:
        result = execute_call_import_delete_chunk(
            db_session, call_import.id, org_id,
        )
        if result["status"] == "completed":
            break

    assert (
        db_session.query(CallImport)
        .filter(CallImport.id == call_import.id)
        .count()
        == 0
    )