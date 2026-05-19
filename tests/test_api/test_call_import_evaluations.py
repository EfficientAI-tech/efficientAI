"""API tests for the per-call-import evaluation routes.

Covers ``POST/GET/DELETE /call-imports/{id}/evaluations`` plus the
``/rows`` listing and CSV ``/export`` endpoints. Both the row-import
worker and the per-row evaluation worker are stubbed so the tests run
without Celery / Redis.
"""

import io
import sys
import types
from uuid import UUID, uuid4

import pytest

from app.models.database import (
    CallImport,
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
    Metric,
    Organization,
    TelephonyIntegration,
    Workspace,
)
from app.models.enums import CallImportRowStatus, CallImportStatus


def _ensure_default_workspace(db_session, org_id):
    ws = (
        db_session.query(Workspace)
        .filter(Workspace.organization_id == org_id, Workspace.is_default.is_(True))
        .first()
    )
    if ws is None:
        ws = Workspace(
            organization_id=org_id, name="Default", slug="default", is_default=True
        )
        db_session.add(ws)
        db_session.commit()
    return ws


@pytest.fixture(autouse=True)
def stub_workers(monkeypatch):
    """Stub the Celery task modules used by the evaluation route."""

    fake_import_module = types.ModuleType("app.workers.tasks.process_call_import_row")

    class _ImportTask:
        @staticmethod
        def delay(*_a, **_kw):
            return types.SimpleNamespace(id="import-task-id")

    fake_import_module.process_call_import_row_task = _ImportTask()

    fake_eval_module = types.ModuleType("app.workers.tasks.evaluate_call_import_row")
    fake_eval_module.evaluate_call_import_row_task = types.SimpleNamespace(
        s=lambda *_a, **_kw: types.SimpleNamespace(args=_a, kwargs=_kw),
    )

    fake_celery = types.ModuleType("celery")
    fake_celery.group = lambda sigs: types.SimpleNamespace(
        apply_async=lambda: types.SimpleNamespace(id="celery-group-id"),
    )

    previous = {
        "app.workers.tasks.process_call_import_row": sys.modules.get(
            "app.workers.tasks.process_call_import_row"
        ),
        "app.workers.tasks.evaluate_call_import_row": sys.modules.get(
            "app.workers.tasks.evaluate_call_import_row"
        ),
        "celery": sys.modules.get("celery"),
    }
    sys.modules["app.workers.tasks.process_call_import_row"] = fake_import_module
    sys.modules["app.workers.tasks.evaluate_call_import_row"] = fake_eval_module
    sys.modules["celery"] = fake_celery
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value


def _make_metric(db_session, org_id, name="Politeness"):
    workspace = _ensure_default_workspace(db_session, org_id)
    metric = Metric(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=workspace.id,
        name=name,
        description=f"{name} description",
        metric_type="rating",
        trigger="always",
        enabled=True,
        supported_surfaces=["agent"],
        enabled_surfaces=["agent"],
    )
    db_session.add(metric)
    db_session.commit()
    return metric


def _make_call_import(
    db_session,
    org_id,
    *,
    rows=2,
    row_status=CallImportRowStatus.COMPLETED,
    column_mapping=None,
    extra_columns=None,
    integration=None,
):
    if integration is None:
        integration = TelephonyIntegration(
            id=uuid4(),
            organization_id=org_id,
            provider="exotel",
            auth_id="enc",
            auth_token="enc",
            is_active=True,
            is_default=True,
        )
        db_session.add(integration)
        db_session.commit()

    workspace = _ensure_default_workspace(db_session, org_id)
    call_import = CallImport(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=workspace.id,
        provider="exotel",
        telephony_integration_id=integration.id,
        original_filename="batch.csv",
        column_mapping=column_mapping
        or {
            "external_call_id": "CallID",
            "transcript": "Transcript",
            "recording_url": "Recording URL",
        },
        extra_columns=extra_columns or [],
        total_rows=rows,
        completed_rows=rows if row_status == CallImportRowStatus.COMPLETED else 0,
        failed_rows=0,
        status=CallImportStatus.COMPLETED,
    )
    db_session.add(call_import)
    db_session.flush()

    row_models = []
    for idx in range(rows):
        row = CallImportRow(
            id=uuid4(),
            call_import_id=call_import.id,
            organization_id=org_id,
            row_index=idx,
            external_call_id=f"ext-{idx}",
            transcript=f"transcript-{idx}",
            recording_url=None,
            raw_columns={
                "CallID": f"ext-{idx}",
                "Transcript": f"transcript-{idx}",
                "Recording URL": "",
            },
            status=row_status,
        )
        db_session.add(row)
        row_models.append(row)
    db_session.commit()
    return call_import, row_models


def test_create_evaluation_happy_path(authenticated_client, db_session, org_id, seed_org):
    metric = _make_metric(db_session, org_id)
    call_import, _rows = _make_call_import(db_session, org_id, rows=2)

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json={"metric_ids": [str(metric.id)]},
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "running"
    assert body["total_rows"] == 2
    assert body["metrics"][0]["name"] == metric.name
    assert body["selected_metric_ids"] == [str(metric.id)]


def test_create_evaluation_rejects_foreign_metric(
    authenticated_client, db_session, org_id, seed_org
):
    # A real "other" organization is needed so the metric's FK to
    # organizations is satisfied on engines that enforce FKs (e.g. Postgres).
    other_org = Organization(id=uuid4(), name="Other Org")
    db_session.add(other_org)
    db_session.commit()

    # Foreign org needs its own workspace so the metric FK to workspaces
    # is satisfied.
    other_workspace = _ensure_default_workspace(db_session, other_org.id)
    # Metric owned by a *different* org -> rejected.
    other_org_metric = Metric(
        id=uuid4(),
        organization_id=other_org.id,
        workspace_id=other_workspace.id,
        name="ForeignMetric",
        metric_type="rating",
        trigger="always",
        enabled=True,
        supported_surfaces=["agent"],
        enabled_surfaces=["agent"],
    )
    db_session.add(other_org_metric)
    db_session.commit()

    call_import, _ = _make_call_import(db_session, org_id)

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json={"metric_ids": [str(other_org_metric.id)]},
    )
    assert response.status_code == 400
    # Foreign-org metric => "do not exist in your organization".
    assert "do not exist" in response.json()["detail"].lower()


def test_create_evaluation_with_both_sources_creates_two_runs(
    authenticated_client, db_session, org_id, seed_org
):
    """Ticking both Production and Diarised in the modal must create two
    separate evaluation runs and the response should link them via
    ``sibling_evaluation_ids`` so the frontend can navigate to either."""
    metric = _make_metric(db_session, org_id)
    call_import, _rows = _make_call_import(db_session, org_id, rows=1)

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json={
            "metric_ids": [str(metric.id)],
            "transcript_sources": ["production", "diarised"],
        },
    )
    assert response.status_code == 202, response.text
    body = response.json()
    # Primary run is the first requested source (production) and it knows
    # about its diarised sibling.
    assert body["transcript_source"] == "production"
    assert len(body["sibling_evaluation_ids"]) == 1

    # Both runs persisted to the DB under the same call import.
    all_runs = (
        db_session.query(CallImportEvaluation)
        .filter(CallImportEvaluation.call_import_id == call_import.id)
        .all()
    )
    assert len(all_runs) == 2
    sources = {row.transcript_source for row in all_runs}
    assert sources == {"production", "diarised"}


def test_create_evaluation_defaults_to_production_source(
    authenticated_client, db_session, org_id, seed_org
):
    """Legacy clients that omit transcript_sources still get exactly ONE
    evaluation run scored against the production transcript."""
    metric = _make_metric(db_session, org_id)
    call_import, _ = _make_call_import(db_session, org_id, rows=1)

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json={"metric_ids": [str(metric.id)]},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["transcript_source"] == "production"
    assert body["sibling_evaluation_ids"] == []


def test_create_evaluation_marks_completed_when_no_rows(
    authenticated_client, db_session, org_id, seed_org
):
    metric = _make_metric(db_session, org_id)
    # Use PENDING rows so none qualify.
    call_import, _ = _make_call_import(
        db_session, org_id, rows=2, row_status=CallImportRowStatus.PENDING
    )

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json={"metric_ids": [str(metric.id)]},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "completed"
    assert body["total_rows"] == 0


def test_list_and_get_evaluations(
    authenticated_client, db_session, org_id, seed_org
):
    metric = _make_metric(db_session, org_id)
    call_import, _ = _make_call_import(db_session, org_id, rows=1)

    created = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json={"metric_ids": [str(metric.id)]},
    ).json()

    listing = authenticated_client.get(
        f"/api/v1/call-imports/{call_import.id}/evaluations"
    )
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == created["id"]

    detail = authenticated_client.get(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{created['id']}"
    )
    assert detail.status_code == 200
    assert detail.json()["id"] == created["id"]


def test_delete_evaluation_removes_row_results(
    authenticated_client, db_session, org_id, seed_org
):
    metric = _make_metric(db_session, org_id)
    call_import, _ = _make_call_import(db_session, org_id, rows=1)
    created = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json={"metric_ids": [str(metric.id)]},
    ).json()

    response = authenticated_client.delete(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{created['id']}"
    )
    assert response.status_code == 204

    created_uuid = UUID(created["id"])
    leftover_parents = (
        db_session.query(CallImportEvaluation)
        .filter(CallImportEvaluation.id == created_uuid)
        .count()
    )
    leftover_rows = (
        db_session.query(CallImportEvaluationRow)
        .filter(CallImportEvaluationRow.evaluation_id == created_uuid)
        .count()
    )
    assert leftover_parents == 0
    assert leftover_rows == 0


def test_export_csv_uses_raw_columns_and_metric_names(
    authenticated_client, db_session, org_id, seed_org
):
    metric = _make_metric(db_session, org_id, name="Empathy")
    call_import, source_rows = _make_call_import(
        db_session,
        org_id,
        rows=2,
        column_mapping={
            "external_call_id": "CallID",
            "transcript": "Transcript",
            "recording_url": "Recording URL",
        },
        extra_columns=["AgentName"],
    )
    # Augment the raw_columns snapshot so AgentName has a real value.
    for row in source_rows:
        row.raw_columns = {**row.raw_columns, "AgentName": "Alice"}
    db_session.commit()

    created = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json={"metric_ids": [str(metric.id)]},
    ).json()

    # Backfill metric_scores so the export has non-empty columns.
    eval_rows = (
        db_session.query(CallImportEvaluationRow)
        .filter(CallImportEvaluationRow.evaluation_id == UUID(created["id"]))
        .all()
    )
    assert eval_rows, "evaluation row records should have been created"
    for eval_row in eval_rows:
        eval_row.metric_scores = {
            str(metric.id): {
                "value": 4,
                "type": "rating",
                "metric_name": metric.name,
            }
        }
    db_session.commit()

    response = authenticated_client.get(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{created['id']}/export"
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")

    csv_text = response.text
    lines = [line for line in csv_text.splitlines() if line]
    assert lines, "CSV export should not be empty"

    header_cols = lines[0].split(",")
    # User-supplied header order is preserved before metric columns.
    assert header_cols[0] == "CallID"
    assert "Transcript" in header_cols
    assert "Recording URL" in header_cols
    assert "AgentName" in header_cols
    assert header_cols[-1] == "Empathy"

    # Every data row should carry the metric value (4).
    for line in lines[1:]:
        assert line.endswith(",4")


def test_export_unknown_evaluation_returns_404(
    authenticated_client, db_session, org_id, seed_org
):
    call_import, _ = _make_call_import(db_session, org_id, rows=1)
    response = authenticated_client.get(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{uuid4()}/export"
    )
    assert response.status_code == 404


def test_evaluations_unknown_import_returns_404(authenticated_client, seed_org):
    response = authenticated_client.get(
        f"/api/v1/call-imports/{uuid4()}/evaluations"
    )
    assert response.status_code == 404
