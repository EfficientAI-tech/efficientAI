"""Tests for guarded CallImportEvaluation status updates during delete."""

import types
import sys
from uuid import uuid4

from sqlalchemy import update

from app.models.database import (
    CallImport,
    CallImportEvaluation,
    CallImportRow,
)
from app.models.enums import CallImportRowStatus, CallImportStatus
from app.services.call_imports.bulk_ops import materialize_and_enqueue_evaluation
from app.services.call_imports.evaluation_status_guard import (
    evaluation_status_is_deleting,
    update_evaluation_unless_deleting,
)


def _seed_eval(db_session, org_id, workspace_id):
    call_import = CallImport(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=workspace_id,
        status=CallImportStatus.COMPLETED,
        total_rows=1,
        column_mapping={},
    )
    db_session.add(call_import)
    db_session.flush()

    row = CallImportRow(
        id=uuid4(),
        call_import_id=call_import.id,
        organization_id=org_id,
        workspace_id=workspace_id,
        row_index=0,
        conversation_id="c1",
        transcript="hello",
        status=CallImportRowStatus.COMPLETED,
    )
    evaluation = CallImportEvaluation(
        id=uuid4(),
        call_import_id=call_import.id,
        organization_id=org_id,
        workspace_id=workspace_id,
        selected_metric_ids=[],
        status="pending",
        total_rows=0,
        transcript_source="production",
    )
    db_session.add_all([row, evaluation])
    db_session.commit()
    return evaluation, row


def test_update_evaluation_unless_deleting_skips_deleting_row(
    db_session, org_id, default_workspace,
):
    evaluation, _ = _seed_eval(db_session, org_id, default_workspace.id)
    evaluation.status = "deleting"
    db_session.commit()

    applied = update_evaluation_unless_deleting(
        db_session,
        evaluation.id,
        {"status": "running"},
    )
    db_session.commit()
    assert not applied
    assert evaluation_status_is_deleting(db_session, evaluation.id)


def test_update_evaluation_unless_deleting_applies_for_pending(
    db_session, org_id, default_workspace,
):
    evaluation, _ = _seed_eval(db_session, org_id, default_workspace.id)

    applied = update_evaluation_unless_deleting(
        db_session,
        evaluation.id,
        {"status": "completed", "total_rows": 0},
    )
    db_session.commit()
    assert applied
    db_session.refresh(evaluation)
    assert evaluation.status == "completed"
    assert evaluation.total_rows == 0


def test_materialize_preserves_deleting_set_during_materialize(
    db_session,
    org_id,
    default_workspace,
    monkeypatch,
):
    evaluation, _ = _seed_eval(db_session, org_id, default_workspace.id)
    from app.services.call_imports import bulk_ops

    real_bulk = bulk_ops.bulk_insert_evaluation_rows

    def bulk_then_mark_deleting(*args, **kwargs):
        out = real_bulk(*args, **kwargs)
        eval_id = args[2]
        db_session.execute(
            update(CallImportEvaluation)
            .where(CallImportEvaluation.id == eval_id)
            .values(status="deleting")
        )
        db_session.commit()
        return out

    monkeypatch.setattr(bulk_ops, "bulk_insert_evaluation_rows", bulk_then_mark_deleting)
    monkeypatch.setitem(
        sys.modules,
        "app.api.v1.routes.call_import_evaluations",
        types.SimpleNamespace(
            _enqueue_eval_rows_with_optional_transcribe=lambda *_a, **_kw: None,
        ),
    )
    enqueue_calls = []

    def track_enqueue(*_a, **_kw):
        enqueue_calls.append(1)

    monkeypatch.setitem(
        sys.modules,
        "app.api.v1.routes.call_import_evaluations",
        types.SimpleNamespace(
            _enqueue_eval_rows_with_optional_transcribe=track_enqueue,
        ),
    )

    materialize_and_enqueue_evaluation(db_session, evaluation.id)

    db_session.refresh(evaluation)
    assert evaluation.status == "deleting"
    assert enqueue_calls == []