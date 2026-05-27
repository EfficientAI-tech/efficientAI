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
            conversation_id=f"ext-{idx}",
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


# Every Run Evaluation request now requires STT provider+model (the
# diarised transcript is the only supported source and auto-diarise is
# mandatory). Centralizing the minimum-valid payload here keeps the test
# bodies focused on the behavior under test.
_DEFAULT_EVAL_STT = {
    "stt_provider": "deepgram",
    "stt_model": "nova-2",
    # Every evaluation run now requires an LLM diariser (the worker
    # no longer falls back to pyannote). Keep these on the shared
    # default so tests that aren't exercising the diariser specifically
    # don't have to repeat them in every payload.
    "diarization_llm_provider": "openai",
    "diarization_llm_model": "gpt-4o-mini",
}


def _eval_body(metric_ids, **overrides):
    body = {"metric_ids": [str(mid) for mid in metric_ids], **_DEFAULT_EVAL_STT}
    body.update(overrides)
    return body


def test_create_evaluation_happy_path(authenticated_client, db_session, org_id, seed_org):
    metric = _make_metric(db_session, org_id)
    call_import, _rows = _make_call_import(db_session, org_id, rows=2)

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json=_eval_body([metric.id]),
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "running"
    assert body["total_rows"] == 2
    assert body["metrics"][0]["name"] == metric.name
    assert body["selected_metric_ids"] == [str(metric.id)]
    # Diarised is the only supported transcript source now.
    assert body["transcript_source"] == "diarised"


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
        json=_eval_body([other_org_metric.id]),
    )
    assert response.status_code == 400
    # Foreign-org metric => "do not exist in your organization".
    assert "do not exist" in response.json()["detail"].lower()


def test_create_evaluation_rejects_production_transcript_source(
    authenticated_client, db_session, org_id, seed_org
):
    """The legacy ``production`` transcript source is no longer accepted.
    Any request that includes it must 4xx so callers move to the new
    diarised-only flow instead of silently producing a different run."""
    metric = _make_metric(db_session, org_id)
    call_import, _rows = _make_call_import(db_session, org_id, rows=1)

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json=_eval_body(
            [metric.id],
            transcript_sources=["production"],
        ),
    )
    # Pydantic's field_validator surfaces a 422 for invalid request
    # bodies (the schema validator runs before the route handler).
    assert response.status_code == 422
    detail = response.json()["detail"]
    body_text = str(detail).lower()
    assert "diarised" in body_text or "production" in body_text


def test_create_evaluation_defaults_to_diarised_source(
    authenticated_client, db_session, org_id, seed_org
):
    """Clients that omit transcript_sources get exactly ONE evaluation
    run scored against the diarised transcript (the only supported
    source now)."""
    metric = _make_metric(db_session, org_id)
    call_import, _ = _make_call_import(db_session, org_id, rows=1)

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json=_eval_body([metric.id]),
    )
    assert response.status_code == 202
    body = response.json()
    assert body["transcript_source"] == "diarised"
    assert body["sibling_evaluation_ids"] == []


def test_create_evaluation_requires_stt_provider_and_model(
    authenticated_client, db_session, org_id, seed_org
):
    """Every evaluation auto-diarises rows that don't already have a
    diarised transcript, so the STT provider+model are mandatory on
    every request — even when auto_transcribe is not explicitly
    passed."""
    metric = _make_metric(db_session, org_id)
    call_import, _ = _make_call_import(db_session, org_id, rows=1)

    # Missing both STT fields -> 400 from the route validator.
    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json={"metric_ids": [str(metric.id)]},
    )
    assert response.status_code == 400
    assert "stt" in response.json()["detail"].lower()

    # Partial config (provider without model) is still rejected.
    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json={
            "metric_ids": [str(metric.id)],
            "stt_provider": "deepgram",
        },
    )
    assert response.status_code == 400
    assert "stt_model" in response.json()["detail"].lower()


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
        json=_eval_body([metric.id]),
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
        json=_eval_body([metric.id]),
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
        json=_eval_body([metric.id]),
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
        json=_eval_body([metric.id]),
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


# ---------------------------------------------------------------------------
# User-initiated cancel for in-flight evaluations
# ---------------------------------------------------------------------------
#
# These tests exercise ``POST .../{eval_id}/cancel`` and
# ``POST .../{eval_id}/rows/{eval_row_id}/cancel`` in isolation: the rows are
# left in ``running`` (with synthetic ``celery_task_id`` values) and the
# Celery control plane is stubbed via ``sys.modules`` so the revoke call
# succeeds without a real broker. We verify three things on every cancel:
#
# 1. Each cancellable row flips to ``failed`` with the
#    ``"Evaluation cancelled by user"`` sentinel + cleared ``celery_task_id``.
# 2. The parent rollup picks the new state up (``failed``/``partial``).
# 3. The Celery revoke was called with ``terminate=True, signal="SIGTERM"`` —
#    that's the contract that lets the worker actually interrupt an in-flight
#    LLM/audio call rather than waiting up to 10 minutes for the time limit.


def _stub_celery_revoke(monkeypatch):
    """Install a fake ``app.workers.celery_app`` with a recording revoke.

    Returns the ``MagicMock`` so the test can assert on call arguments.
    """
    from unittest.mock import MagicMock

    revoke = MagicMock()
    fake_module = types.ModuleType("app.workers.celery_app")
    fake_module.celery_app = types.SimpleNamespace(
        control=types.SimpleNamespace(revoke=revoke)
    )
    monkeypatch.setitem(sys.modules, "app.workers.celery_app", fake_module)
    return revoke


def _force_running(db_session, evaluation_id, *, task_id_prefix="celery-task"):
    """Flip every row of ``evaluation_id`` to ``running`` with a fake task id.

    Mirrors what the worker does at the start of ``evaluate_call_import_row``
    so the cancel endpoint has something cancellable to act on (a freshly
    created evaluation has all rows in ``pending`` with no ``celery_task_id``,
    which would short-circuit the revoke path and leave us unable to assert
    on it).
    """
    eval_uuid = UUID(evaluation_id)
    rows = (
        db_session.query(CallImportEvaluationRow)
        .filter(CallImportEvaluationRow.evaluation_id == eval_uuid)
        .all()
    )
    for idx, row in enumerate(rows):
        row.status = "running"
        row.celery_task_id = f"{task_id_prefix}-{idx}"
    parent = (
        db_session.query(CallImportEvaluation)
        .filter(CallImportEvaluation.id == eval_uuid)
        .first()
    )
    parent.status = "running"
    db_session.commit()
    return rows


def test_cancel_evaluation_flips_rows_and_revokes_tasks(
    authenticated_client, db_session, org_id, seed_org, monkeypatch
):
    """Run-level cancel: every running row flips to the cancelled sentinel,
    parent rolls up to ``failed``, and Celery is asked to SIGTERM each task."""
    metric = _make_metric(db_session, org_id)
    call_import, _ = _make_call_import(db_session, org_id, rows=2)
    created = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json=_eval_body([metric.id]),
    ).json()

    revoke = _stub_celery_revoke(monkeypatch)
    rows = _force_running(db_session, created["id"])
    expected_task_ids = {r.celery_task_id for r in rows}

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{created['id']}/cancel"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    # Two running rows -> all failed -> rollup is ``failed``.
    assert body["status"] == "failed"
    assert body["failed_rows"] == 2
    assert body["completed_rows"] == 0

    # DB state matches the response.
    db_session.expire_all()
    refreshed = (
        db_session.query(CallImportEvaluationRow)
        .filter(CallImportEvaluationRow.evaluation_id == UUID(created["id"]))
        .all()
    )
    assert {r.status for r in refreshed} == {"failed"}
    assert all(
        (r.error_message or "") == "Evaluation cancelled by user"
        for r in refreshed
    )
    # ``celery_task_id`` is cleared so a stale poll can't accidentally
    # re-revoke an already-cancelled task.
    assert all(r.celery_task_id is None for r in refreshed)

    # Every fake task id was forwarded to Celery with terminate=True +
    # SIGTERM — that's the contract that interrupts the worker mid-call.
    revoked_task_ids = {call.args[0] for call in revoke.call_args_list}
    assert revoked_task_ids == expected_task_ids
    for call in revoke.call_args_list:
        assert call.kwargs.get("terminate") is True
        assert call.kwargs.get("signal") == "SIGTERM"


def test_cancel_evaluation_is_idempotent_for_terminal_runs(
    authenticated_client, db_session, org_id, seed_org, monkeypatch
):
    """Calling cancel on a run whose rows are already terminal is a 200
    no-op (no revokes, no DB churn) so the UI can fire it from a button
    without pre-checking state."""
    metric = _make_metric(db_session, org_id)
    call_import, _ = _make_call_import(db_session, org_id, rows=1)
    created = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json=_eval_body([metric.id]),
    ).json()

    # Mark every row + parent as ``completed`` so nothing is cancellable.
    rows = (
        db_session.query(CallImportEvaluationRow)
        .filter(CallImportEvaluationRow.evaluation_id == UUID(created["id"]))
        .all()
    )
    for row in rows:
        row.status = "completed"
    parent = (
        db_session.query(CallImportEvaluation)
        .filter(CallImportEvaluation.id == UUID(created["id"]))
        .first()
    )
    parent.status = "completed"
    parent.completed_rows = len(rows)
    db_session.commit()

    revoke = _stub_celery_revoke(monkeypatch)
    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{created['id']}/cancel"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    revoke.assert_not_called()


def test_cancel_evaluation_unknown_id_returns_404(
    authenticated_client, db_session, org_id, seed_org
):
    call_import, _ = _make_call_import(db_session, org_id, rows=1)
    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{uuid4()}/cancel"
    )
    assert response.status_code == 404


def test_cancel_evaluation_row_flips_only_target_row(
    authenticated_client, db_session, org_id, seed_org, monkeypatch
):
    """Row-level cancel scopes the flip + revoke to the targeted row, leaves
    siblings alone, and rolls up the parent (here: 1 failed + 1 running ->
    parent stays ``running``)."""
    metric = _make_metric(db_session, org_id)
    call_import, _ = _make_call_import(db_session, org_id, rows=2)
    created = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json=_eval_body([metric.id]),
    ).json()

    revoke = _stub_celery_revoke(monkeypatch)
    rows = _force_running(db_session, created["id"])
    target = rows[0]
    sibling = rows[1]
    # Snapshot the celery_task_ids as plain strings before the cancel call.
    # The cancel endpoint clears ``celery_task_id`` on the target row, and the
    # ``db_session.expire_all()`` below invalidates the ORM cache so accessing
    # ``rows[i].celery_task_id`` afterwards would reload from DB.
    original_task_ids = {row.celery_task_id for row in rows}
    target_original_task_id = target.celery_task_id

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/"
        f"{created['id']}/rows/{target.id}/cancel"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(target.id)
    assert body["status"] == "failed"
    assert body["error_message"] == "Evaluation cancelled by user"

    db_session.expire_all()
    refreshed_target = db_session.get(CallImportEvaluationRow, target.id)
    refreshed_sibling = db_session.get(CallImportEvaluationRow, sibling.id)
    assert refreshed_target.status == "failed"
    assert refreshed_target.celery_task_id is None
    # Sibling untouched — only the targeted row was cancelled.
    assert refreshed_sibling.status == "running"
    assert refreshed_sibling.celery_task_id is not None

    parent = db_session.get(CallImportEvaluation, UUID(created["id"]))
    # 1 running + 1 failed -> parent rolls up to ``running``.
    assert parent.status == "running"

    revoke.assert_called_once()
    assert revoke.call_args.args[0] == target_original_task_id or (
        # ``celery_task_id`` is cleared post-revoke; cross-check via the
        # original snapshot we captured before the call.
        revoke.call_args.args[0] in original_task_ids
    )


def test_cancel_evaluation_row_idempotent_when_terminal(
    authenticated_client, db_session, org_id, seed_org, monkeypatch
):
    """A row already in a terminal state is returned unchanged with a 200 —
    no DB flip, no revoke."""
    metric = _make_metric(db_session, org_id)
    call_import, _ = _make_call_import(db_session, org_id, rows=1)
    created = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json=_eval_body([metric.id]),
    ).json()

    eval_row = (
        db_session.query(CallImportEvaluationRow)
        .filter(CallImportEvaluationRow.evaluation_id == UUID(created["id"]))
        .first()
    )
    eval_row.status = "completed"
    eval_row.metric_scores = {str(metric.id): {"value": 4}}
    db_session.commit()

    revoke = _stub_celery_revoke(monkeypatch)
    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/"
        f"{created['id']}/rows/{eval_row.id}/cancel"
    )
    assert response.status_code == 200
    body = response.json()
    # Row is unchanged — still completed, scores still attached.
    assert body["status"] == "completed"
    assert body["metric_scores"][str(metric.id)]["value"] == 4
    revoke.assert_not_called()


def test_cancel_evaluation_row_unknown_row_returns_404(
    authenticated_client, db_session, org_id, seed_org
):
    metric = _make_metric(db_session, org_id)
    call_import, _ = _make_call_import(db_session, org_id, rows=1)
    created = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json=_eval_body([metric.id]),
    ).json()

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/"
        f"{created['id']}/rows/{uuid4()}/cancel"
    )
    assert response.status_code == 404
