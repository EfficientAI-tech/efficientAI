"""Daily auto-abort selects stale running evaluations and reuses abort."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.models.database import (
    CallImport,
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
    Organization,
    Workspace,
)
from app.models.enums import CallImportRowStatus, CallImportStatus
from app.services.call_imports.bulk_ops import execute_evaluation_cancel
from app.workers.concurrency.eval_dispatch import recover_eval_row_for_eval_chain
from app.workers.tasks.evaluate_call_import_row_core import (
    AUTO_ABORTED_STATUS,
    EVAL_AUTO_ABORTED_ERROR,
    _apply_parent_status_from_counters,
)
from app.workers.tasks.sweep_stale_evaluations import (
    enqueue_stale_evaluation_aborts,
    evaluation_is_stale_running,
    list_stale_running_evaluation_ids,
)


def _silence(monkeypatch):
    monkeypatch.setattr(
        "app.db_sharding.sessions.is_sharding_enabled",
        lambda: False,
    )
    monkeypatch.setattr(
        "app.services.call_imports.bulk_ops.is_sharding_enabled",
        lambda: False,
    )
    monkeypatch.setattr(
        "app.services.call_imports.eval_flexprice_billing.maybe_finalize_evaluation_flexprice_billing",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "app.services.call_imports.progress_counters.clear_eval_progress_redis",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "app.services.call_imports.evaluation_bulk_op.clear_evaluation_bulk_operation",
        lambda *_args, **_kwargs: None,
    )


def _eval(db, org, workspace, row_statuses, *, started_at, created_at=None, status="running"):
    call_import = CallImport(
        id=uuid4(),
        organization_id=org.id,
        workspace_id=workspace.id,
        original_filename="rows.csv",
        total_rows=len(row_statuses),
        status=CallImportStatus.COMPLETED,
    )
    db.add(call_import)
    db.flush()
    evaluation = CallImportEvaluation(
        id=uuid4(),
        call_import_id=call_import.id,
        organization_id=org.id,
        workspace_id=workspace.id,
        selected_metric_ids=[],
        status=status,
        total_rows=len(row_statuses),
        completed_rows=0,
        failed_rows=0,
        started_at=started_at,
        created_at=created_at or datetime.now(timezone.utc),
    )
    db.add(evaluation)
    db.flush()
    rows = []
    for index, row_status in enumerate(row_statuses):
        source = CallImportRow(
            id=uuid4(),
            call_import_id=call_import.id,
            organization_id=org.id,
            workspace_id=workspace.id,
            row_index=index,
            conversation_id=f"c-{index}-{uuid4().hex[:8]}",
            status=CallImportRowStatus.COMPLETED,
        )
        db.add(source)
        db.flush()
        eval_row = CallImportEvaluationRow(
            id=uuid4(),
            evaluation_id=evaluation.id,
            call_import_row_id=source.id,
            workspace_id=workspace.id,
            status=row_status,
            metric_scores={},
        )
        db.add(eval_row)
        rows.append(eval_row)
    db.commit()
    return evaluation, rows


def test_auto_abort_fails_leftover_rows_and_keeps_the_status(
    db_session, seed_org, default_workspace, monkeypatch
):
    _silence(monkeypatch)
    old = datetime.now(timezone.utc) - timedelta(hours=25)
    evaluation, rows = _eval(
        db_session,
        seed_org,
        default_workspace,
        ["completed", "pending"],
        started_at=old,
    )

    result = execute_evaluation_cancel(
        db_session,
        evaluation.id,
        mode="abort",
        row_error_message=EVAL_AUTO_ABORTED_ERROR,
        sticky_status=AUTO_ABORTED_STATUS,
    )

    assert result["cancelled"] == 1
    db_session.refresh(evaluation)
    assert evaluation.status == "auto_aborted"
    assert evaluation.finished_at is not None
    assert evaluation.completed_rows == 1
    assert evaluation.failed_rows == 1
    db_session.refresh(rows[0])
    db_session.refresh(rows[1])
    assert rows[0].status == "completed"
    assert rows[1].status == "failed"
    assert rows[1].error_message == EVAL_AUTO_ABORTED_ERROR
    recover_eval_row_for_eval_chain(rows[1])
    assert rows[1].status == "failed"


def test_auto_abort_leaves_a_finished_parent_on_the_rollup_status(
    db_session, seed_org, default_workspace, monkeypatch
):
    _silence(monkeypatch)
    old = datetime.now(timezone.utc) - timedelta(hours=30)
    evaluation, _rows = _eval(
        db_session,
        seed_org,
        default_workspace,
        ["completed", "failed"],
        started_at=old,
    )

    result = execute_evaluation_cancel(
        db_session,
        evaluation.id,
        mode="abort",
        row_error_message=EVAL_AUTO_ABORTED_ERROR,
        sticky_status=AUTO_ABORTED_STATUS,
    )

    assert result["cancelled"] == 0
    db_session.refresh(evaluation)
    assert evaluation.status == "partial"
    assert evaluation.completed_rows == 1
    assert evaluation.failed_rows == 1


def test_sticky_abort_does_not_touch_a_parent_that_is_not_running(
    db_session, seed_org, default_workspace, monkeypatch
):
    _silence(monkeypatch)
    evaluation, rows = _eval(
        db_session,
        seed_org,
        default_workspace,
        ["completed", "pending"],
        started_at=datetime.now(timezone.utc) - timedelta(hours=48),
        status="partial",
    )

    result = execute_evaluation_cancel(
        db_session,
        evaluation.id,
        mode="abort",
        row_error_message=EVAL_AUTO_ABORTED_ERROR,
        sticky_status=AUTO_ABORTED_STATUS,
    )

    assert result["cancelled"] == 0
    db_session.refresh(evaluation)
    db_session.refresh(rows[1])
    assert evaluation.status == "partial"
    assert rows[1].status == "pending"


def test_enqueue_is_org_wide_and_skips_runs_younger_than_24_hours(
    db_session, seed_org, default_workspace, monkeypatch
):
    now = datetime.now(timezone.utc)
    old = now - timedelta(hours=26)
    young = now - timedelta(hours=2)
    other_workspace = Workspace(
        id=uuid4(),
        organization_id=seed_org.id,
        name="Other",
        slug=f"other-{uuid4().hex[:8]}",
        is_default=False,
    )
    db_session.add(other_workspace)
    db_session.commit()
    other_org = Organization(id=uuid4(), name="Other org")
    db_session.add(other_org)
    db_session.commit()
    other_ws = Workspace(
        id=uuid4(),
        organization_id=other_org.id,
        name="Default",
        slug=f"default-{uuid4().hex[:8]}",
        is_default=True,
    )
    db_session.add(other_ws)
    db_session.commit()

    stale_default, _ = _eval(
        db_session, seed_org, default_workspace, ["pending"], started_at=old
    )
    stale_other_ws, _ = _eval(
        db_session, seed_org, other_workspace, ["running"], started_at=old
    )
    young_same_org, _ = _eval(
        db_session, seed_org, default_workspace, ["pending"], started_at=young
    )
    stale_other_org, _ = _eval(
        db_session, other_org, other_ws, ["pending"], started_at=old
    )
    missing_started_at, _ = _eval(
        db_session,
        seed_org,
        default_workspace,
        ["pending"],
        started_at=None,
        created_at=old,
    )
    fresh_without_started_at, _ = _eval(
        db_session,
        seed_org,
        other_workspace,
        ["pending"],
        started_at=None,
        created_at=young,
    )

    selected = {
        evaluation_id
        for _org_id, evaluation_id in list_stale_running_evaluation_ids(
            db_session, now=now
        )
    }
    assert stale_default.id in selected
    assert stale_other_ws.id in selected
    assert stale_other_org.id in selected
    assert missing_started_at.id in selected
    assert young_same_org.id not in selected
    assert fresh_without_started_at.id not in selected
    assert evaluation_is_stale_running(db_session, young_same_org.id, now=now) is False
    assert evaluation_is_stale_running(db_session, stale_default.id, now=now) is True

    enqueued = []
    held = {stale_other_ws.id}

    def _claim(evaluation_id, _operation):
        return evaluation_id not in held

    monkeypatch.setattr(
        "app.services.call_imports.evaluation_bulk_op.try_set_evaluation_bulk_operation",
        _claim,
    )
    monkeypatch.setattr(
        "app.workers.tasks.sweep_stale_evaluations.auto_abort_stale_evaluation_task.delay",
        lambda evaluation_id: enqueued.append(evaluation_id),
    )

    assert enqueue_stale_evaluation_aborts(db_session, now=now) == 3
    assert set(enqueued) == {
        str(stale_default.id),
        str(stale_other_org.id),
        str(missing_started_at.id),
    }


def test_later_rollup_keeps_auto_aborted():
    evaluation = CallImportEvaluation(
        status="auto_aborted",
        total_rows=2,
        completed_rows=1,
        failed_rows=1,
    )
    _apply_parent_status_from_counters(evaluation)
    assert evaluation.status == "auto_aborted"
    assert evaluation.finished_at is not None
