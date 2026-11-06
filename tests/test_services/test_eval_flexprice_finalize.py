"""Finalize Flexprice billing when an evaluation has no rows in flight."""

from uuid import uuid4

from app.models.database import CallImportEvaluation
from app.services.call_imports.eval_flexprice_billing import (
    maybe_finalize_evaluation_flexprice_billing,
)


def test_finalize_skips_while_rows_in_flight(db_session, monkeypatch):
    flush_calls = []
    monkeypatch.setattr(
        "app.services.call_imports.eval_flexprice_billing.flush_recording_minutes_remainder",
        lambda eid: flush_calls.append(eid) or True,
    )

    evaluation = CallImportEvaluation(
        id=uuid4(),
        organization_id=uuid4(),
        workspace_id=uuid4(),
        call_import_id=uuid4(),
        total_rows=10,
        completed_rows=3,
        failed_rows=2,
        billed_completed_rows=0,
    )

    maybe_finalize_evaluation_flexprice_billing(db_session, evaluation)

    assert flush_calls == []


def test_finalize_flushes_remainder_when_terminal(
    db_session, seed_org, default_workspace, monkeypatch
):
    from app.models.database import CallImport
    from app.models.enums import CallImportStatus

    eval_id = uuid4()
    call_import = CallImport(
        id=uuid4(),
        organization_id=seed_org.id,
        workspace_id=default_workspace.id,
        original_filename="t.csv",
        total_rows=300,
        status=CallImportStatus.COMPLETED,
    )
    db_session.add(call_import)
    db_session.flush()

    flush_calls = []
    monkeypatch.setattr(
        "app.services.call_imports.eval_flexprice_billing.flush_recording_minutes_remainder",
        lambda eid: flush_calls.append(eid) or True,
    )
    monkeypatch.setattr(
        "app.services.call_imports.eval_flexprice_billing.buffer_call_import_evaluation_pass",
        lambda *_a, **_k: True,
    )

    evaluation = CallImportEvaluation(
        id=eval_id,
        organization_id=seed_org.id,
        workspace_id=default_workspace.id,
        call_import_id=call_import.id,
        total_rows=300,
        completed_rows=11,
        failed_rows=289,
        billed_completed_rows=0,
        selected_metric_ids=[],
        status="partial",
    )
    db_session.add(evaluation)
    db_session.commit()

    maybe_finalize_evaluation_flexprice_billing(db_session, evaluation)

    assert flush_calls == [eval_id]
    assert evaluation.billed_completed_rows == 11


def test_rollup_evaluation_status_finalizes_on_abort_reconcile(
    db_session, seed_org, default_workspace, monkeypatch
):
    from app.api.v1.routes.call_import_evaluations._shared import (
        _rollup_evaluation_status,
    )
    from app.models.database import CallImport
    from app.models.enums import CallImportStatus

    eval_id = uuid4()
    call_import = CallImport(
        id=uuid4(),
        organization_id=seed_org.id,
        workspace_id=default_workspace.id,
        original_filename="t.csv",
        total_rows=10,
        status=CallImportStatus.COMPLETED,
    )
    db_session.add(call_import)
    db_session.flush()

    evaluation = CallImportEvaluation(
        id=eval_id,
        organization_id=seed_org.id,
        workspace_id=default_workspace.id,
        call_import_id=call_import.id,
        status="cancelled",
        total_rows=10,
        completed_rows=4,
        failed_rows=6,
        billed_completed_rows=0,
        selected_metric_ids=[],
    )
    db_session.add(evaluation)
    db_session.commit()

    finalize_calls = []
    monkeypatch.setattr(
        "app.services.call_imports.eval_flexprice_billing.maybe_finalize_evaluation_flexprice_billing",
        lambda db, ev: finalize_calls.append(ev.id),
    )
    monkeypatch.setattr(
        "app.workers.tasks.evaluate_call_import_row_core.reconcile_evaluation_counters",
        lambda _db, ev: None,
    )
    monkeypatch.setattr(
        "app.workers.tasks.evaluate_call_import_row_core._apply_parent_status_from_counters",
        lambda ev: setattr(ev, "status", "partial"),
    )

    _rollup_evaluation_status(evaluation, db_session)

    assert finalize_calls == [eval_id]
