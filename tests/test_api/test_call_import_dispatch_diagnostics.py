"""Tests for call-import eval dispatch operator diagnostics."""

from uuid import uuid4

import pytest

from app.models.database import (
    CallImport,
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
    Workspace,
)
from app.models.enums import CallImportRowStatus, CallImportStatus


@pytest.fixture
def second_workspace(db_session, org_id):
    ws = Workspace(
        id=uuid4(),
        organization_id=org_id,
        name="Secondary",
        slug="secondary",
        is_default=False,
    )
    db_session.add(ws)
    db_session.commit()
    return ws


def _seed_pending_eval(
    db_session,
    org_id,
    workspace_id,
    *,
    pending_rows=3,
    running_rows=0,
):
    call_import = CallImport(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=workspace_id,
        original_filename="batch.csv",
        column_mapping={"external_call_id": "CallID"},
        total_rows=pending_rows + running_rows,
        completed_rows=0,
        failed_rows=0,
        status=CallImportStatus.PROCESSING,
    )
    db_session.add(call_import)
    db_session.flush()

    evaluation = CallImportEvaluation(
        id=uuid4(),
        call_import_id=call_import.id,
        organization_id=org_id,
        workspace_id=workspace_id,
        selected_metric_ids=[str(uuid4())],
        status="running",
        total_rows=pending_rows + running_rows,
    )
    db_session.add(evaluation)
    db_session.flush()

    for idx in range(pending_rows + running_rows):
        source = CallImportRow(
            id=uuid4(),
            call_import_id=call_import.id,
            organization_id=org_id,
            row_index=idx,
            conversation_id=f"ext-{idx}",
            transcript=f"t-{idx}",
            status=CallImportRowStatus.PENDING,
        )
        db_session.add(source)
        db_session.flush()
        eval_row = CallImportEvaluationRow(
            id=uuid4(),
            evaluation_id=evaluation.id,
            call_import_row_id=source.id,
            status="pending" if idx < pending_rows else "running",
            celery_task_id=None if idx < pending_rows else f"task-{idx}",
        )
        db_session.add(eval_row)
    db_session.commit()
    return evaluation


def test_dispatch_diagnostics_groups_pending_rows_by_workspace(
    db_session,
    org_id,
    default_workspace,
    second_workspace,
    monkeypatch,
):
    from app.services.call_imports.dispatch_diagnostics import (
        build_call_import_dispatch_diagnostics,
    )

    _seed_pending_eval(
        db_session,
        org_id,
        default_workspace.id,
        pending_rows=2,
        running_rows=1,
    )
    _seed_pending_eval(
        db_session,
        org_id,
        second_workspace.id,
        pending_rows=5,
    )

    monkeypatch.setattr(
        "app.services.call_imports.dispatch_diagnostics.read_global_inflight",
        lambda: 40,
    )
    monkeypatch.setattr(
        "app.services.call_imports.dispatch_diagnostics.read_org_inflight",
        lambda _org: 40,
    )
    monkeypatch.setattr(
        "app.services.call_imports.dispatch_diagnostics.read_workspace_inflight",
        lambda ws_id: 10 if ws_id == second_workspace.id else 2,
    )
    monkeypatch.setattr(
        "app.services.call_imports.dispatch_diagnostics.read_job_inflight",
        lambda _eval: 0,
    )
    monkeypatch.setattr(
        "app.services.call_imports.dispatch_diagnostics.read_fair_dispatch_state",
        lambda: {
            "global_rr_cursor": 1,
            "dispatch_dedupe_active": False,
            "dispatch_queue": "celery",
            "at_capacity_backoff_seconds": 15,
        },
    )
    monkeypatch.setattr(
        "app.services.call_imports.dispatch_diagnostics.read_workspace_eval_rr_cursor",
        lambda _ws: 0,
    )

    payload = build_call_import_dispatch_diagnostics(db_session, org_id)
    assert payload["limits"]["global_inflight"] == 40
    assert payload["fair_dispatch"]["dispatch_queue"] == "celery"
    assert len(payload["workspaces"]) == 2

    by_id = {item["workspace_id"]: item for item in payload["workspaces"]}
    assert by_id[default_workspace.id]["pending_dispatch_rows"] == 2
    assert by_id[second_workspace.id]["pending_dispatch_rows"] == 5
    assert by_id[second_workspace.id]["inflight"] == 10
    assert by_id[second_workspace.id]["active_evaluations"] == 1


def test_dispatch_diagnostics_api_requires_admin(
    authenticated_client,
    monkeypatch,
):
    from app.core.auth.rbac import require_admin

    monkeypatch.setattr(
        "app.api.v1.routes.call_imports.build_call_import_dispatch_diagnostics",
        lambda *_args, **_kwargs: {
            "limits": {
                "global_limit": 128,
                "global_inflight": 0,
                "global_at_capacity": False,
                "org_limit": 128,
                "org_inflight": 0,
                "org_at_capacity": False,
                "workspace_limit": 100,
                "job_limit": 75,
                "fair_dispatch_batch_size": 75,
            },
            "fair_dispatch": {
                "global_rr_cursor": 0,
                "dispatch_dedupe_active": False,
                "dispatch_queue": "celery",
                "at_capacity_backoff_seconds": 15,
            },
            "workspaces": [],
            "generated_at": "2026-07-15T12:00:00+00:00",
        },
    )

    response = authenticated_client.get("/api/v1/call-imports/dispatch-diagnostics")
    assert response.status_code == 403

    authenticated_client.app.dependency_overrides[require_admin] = lambda: object()
    try:
        response = authenticated_client.get("/api/v1/call-imports/dispatch-diagnostics")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["fair_dispatch"]["dispatch_queue"] == "celery"
        assert body["limits"]["global_limit"] == 128
    finally:
        authenticated_client.app.dependency_overrides.pop(require_admin, None)
