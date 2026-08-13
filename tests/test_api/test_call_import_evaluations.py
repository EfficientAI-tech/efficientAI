"""API tests for the per-call-import evaluation routes.

Covers ``POST/GET/DELETE /call-imports/{id}/evaluations`` plus the
``/rows`` listing and CSV ``/export`` endpoints. Both the row-import
worker and the per-row evaluation worker are stubbed so the tests run
without Celery / Redis.
"""

import io
import importlib.util
import sys
import types
from pathlib import Path
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


def _ensure_eval_worker_import_stubs() -> None:
    """Avoid circular imports while loading ``evaluate_call_import_row_core``."""
    tasks_root = Path(__file__).resolve().parents[2] / "app" / "workers" / "tasks"
    if "app.workers.tasks" not in sys.modules:
        tasks_pkg = types.ModuleType("app.workers.tasks")
        tasks_pkg.__path__ = [str(tasks_root)]
        sys.modules["app.workers.tasks"] = tasks_pkg
    if "app.workers.tasks.evaluate_call_import_row" not in sys.modules:
        sys.modules["app.workers.tasks.evaluate_call_import_row"] = types.ModuleType(
            "app.workers.tasks.evaluate_call_import_row"
        )


def _load_eval_row_core_module():
    """Load rollup helpers from disk; API tests stub ``app.workers.tasks``."""
    _ensure_eval_worker_import_stubs()
    module_name = "app.workers.tasks.evaluate_call_import_row_core"
    existing = sys.modules.get(module_name)
    if existing is not None and hasattr(existing, "reconcile_evaluation_counters"):
        return existing

    module_path = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "workers"
        / "tasks"
        / "evaluate_call_import_row_core.py"
    )
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load task module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


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

    fake_dispatch_module = types.ModuleType("app.workers.concurrency.eval_dispatch")

    class _DispatchTask:
        @staticmethod
        def apply_async(*_a, **_kw):
            return types.SimpleNamespace(id="dispatch-task-id")

    fake_dispatch_module.dispatch_evaluation_rows_task = _DispatchTask()
    fake_dispatch_module.schedule_evaluation_dispatch = lambda *_a, **_kw: None
    fake_dispatch_module._needs_transcribe_for_eval = lambda *_a, **_kw: False
    fake_dispatch_module.DIARIZATION_QUEUE = "diarization"
    fake_dispatch_module.EVALUATIONS_QUEUE = "evaluations"
    fake_dispatch_module.IMPORTS_QUEUE = "imports"

    fake_fair_module = types.ModuleType("app.workers.concurrency.fair_dispatch")
    fake_fair_module.schedule_fair_dispatch = lambda *_a, **_kw: None
    fake_fair_module.store_row_restricted_metrics = lambda *_a, **_kw: None
    fake_fair_module.store_evaluation_transcribe_overwrite = lambda *_a, **_kw: None
    fake_fair_module.read_fair_dispatch_state = lambda: {
        "global_rr_cursor": 0,
        "dispatch_dedupe_active": False,
        "dispatch_queue": "celery",
        "at_capacity_backoff_seconds": 15,
    }
    fake_fair_module.read_workspace_eval_rr_cursor = lambda _workspace_id: 0
    fake_fair_module.finish_eval_work_and_redispatch = lambda *_a, **_kw: None

    fake_celery = types.ModuleType("celery")
    fake_celery.group = lambda sigs: types.SimpleNamespace(
        apply_async=lambda: types.SimpleNamespace(id="celery-group-id"),
    )

    fake_eval_core_module = _load_eval_row_core_module()

    previous = {
        "app.workers.tasks.process_call_import_row": sys.modules.get(
            "app.workers.tasks.process_call_import_row"
        ),
        "app.workers.tasks.evaluate_call_import_row": sys.modules.get(
            "app.workers.tasks.evaluate_call_import_row"
        ),
        "app.workers.tasks.evaluate_call_import_row_core": sys.modules.get(
            "app.workers.tasks.evaluate_call_import_row_core"
        ),
        "app.workers.concurrency.eval_dispatch": sys.modules.get(
            "app.workers.concurrency.eval_dispatch"
        ),
        "app.workers.concurrency.fair_dispatch": sys.modules.get(
            "app.workers.concurrency.fair_dispatch"
        ),
        "celery": sys.modules.get("celery"),
    }
    sys.modules["app.workers.tasks.process_call_import_row"] = fake_import_module
    sys.modules["app.workers.tasks.evaluate_call_import_row"] = fake_eval_module
    sys.modules["app.workers.tasks.evaluate_call_import_row_core"] = fake_eval_core_module
    sys.modules["app.workers.concurrency.eval_dispatch"] = fake_dispatch_module
    sys.modules["app.workers.concurrency.fair_dispatch"] = fake_fair_module
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


def _make_manual_audio_call_import(
    db_session,
    org_id,
    *,
    rows=2,
):
    """Manual audio upload batch: recordings already in S3, no column mapping."""
    workspace = _ensure_default_workspace(db_session, org_id)
    call_import = CallImport(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=workspace.id,
        provider=None,
        telephony_integration_id=None,
        original_filename="Manual recordings",
        source_format="audio",
        column_mapping=None,
        total_rows=rows,
        completed_rows=rows,
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
            workspace_id=workspace.id,
            row_index=idx,
            conversation_id=f"manual-{idx}",
            transcript=None,
            recording_url=None,
            raw_columns={"conversation_id": f"manual-{idx}"},
            status=CallImportRowStatus.COMPLETED,
            recording_s3_key=f"org/{org_id}/call-imports/{call_import.id}/{uuid4()}.wav",
            recording_content_type="audio/wav",
            recording_size_bytes=1024,
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


def test_create_evaluation_accepts_production_transcript_source(
    authenticated_client, db_session, org_id, seed_org
):
    """Production transcript runs skip diarisation config requirements."""
    metric = _make_metric(db_session, org_id)
    call_import, _rows = _make_call_import(db_session, org_id, rows=1)

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json=_eval_body(
            [metric.id],
            transcript_sources=["production"],
            auto_transcribe=False,
        ),
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["transcript_source"] == "production"
    assert body["stt_provider"] is None
    assert body.get("diarisation_llm_provider") is None


def test_create_evaluation_accepts_manual_audio_without_recording_url_column(
    authenticated_client, db_session, org_id, seed_org
):
    """Manual audio batches diarise from stored S3 recordings, not CSV URLs."""
    metric = _make_metric(db_session, org_id)
    call_import, _rows = _make_manual_audio_call_import(db_session, org_id, rows=2)

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json=_eval_body([metric.id]),
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["transcript_source"] == "diarised"
    assert body["total_rows"] == 2


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
    every request ΓÇö even when auto_transcribe is not explicitly
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
# 3. The Celery revoke was called with ``terminate=True, signal="SIGTERM"`` ΓÇö
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


def _revoked_task_ids_from_calls(revoke) -> set[str]:
    """Collect task ids from single or batch Celery revoke mock calls."""
    ids: set[str] = set()
    for call in revoke.call_args_list:
        arg0 = call.args[0]
        if isinstance(arg0, (list, tuple)):
            ids.update(arg0)
        else:
            ids.add(arg0)
    return ids


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
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["accepted"] is True
    assert body["target_count"] == 2
    assert body["evaluation_id"] == created["id"]

    # DB state after background worker (sync-executed in tests).
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
    assert all(r.celery_task_id is None for r in refreshed)

    parent = (
        db_session.query(CallImportEvaluation)
        .filter(CallImportEvaluation.id == UUID(created["id"]))
        .first()
    )
    assert parent.status == "failed"
    assert parent.failed_rows == 2
    assert parent.completed_rows == 0

    revoked_task_ids = _revoked_task_ids_from_calls(revoke)
    assert revoked_task_ids == expected_task_ids
    for call in revoke.call_args_list:
        assert call.kwargs.get("terminate") is True
        assert call.kwargs.get("signal") == "SIGTERM"


def test_cancel_evaluation_rollup_call_import_from_processing_partial(
    authenticated_client, db_session, org_id, seed_org, monkeypatch
):
    """Aborting an eval must not leave the import batch stuck in ``processing``.

    Eval-primary batches materialize thousands of ``pending`` import rows and
    only fetch a subset before the operator cancels. Once the evaluation run
    is terminal, leftover pending rows must not block the parent rollup.
    """
    metric = _make_metric(db_session, org_id)
    call_import, row_models = _make_call_import(
        db_session,
        org_id,
        rows=5,
        row_status=CallImportRowStatus.PENDING,
    )
    row_models[0].status = CallImportRowStatus.COMPLETED
    call_import.status = CallImportStatus.PROCESSING
    call_import.total_rows = 5
    call_import.completed_rows = 1
    call_import.failed_rows = 0
    db_session.commit()

    created = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json=_eval_body([metric.id]),
    ).json()

    _stub_celery_revoke(monkeypatch)
    _force_running(db_session, created["id"])

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{created['id']}/cancel"
    )
    assert response.status_code == 202, response.text
    assert response.json()["target_count"] == 5

    db_session.expire_all()
    refreshed_import = (
        db_session.query(CallImport)
        .filter(CallImport.id == call_import.id)
        .first()
    )
    assert refreshed_import.status == CallImportStatus.PARTIAL
    assert refreshed_import.completed_rows == 1


def test_cancel_evaluation_is_idempotent_for_terminal_runs(
    authenticated_client, db_session, org_id, seed_org, monkeypatch
):
    """Calling cancel on a run whose rows are already terminal is a 202
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
    assert response.status_code == 202
    body = response.json()
    assert body["target_count"] == 0
    assert body["accepted"] is True
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
    # Sibling untouched ΓÇö only the targeted row was cancelled.
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
    """A row already in a terminal state is returned unchanged with a 200 ΓÇö
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
    # Row is unchanged ΓÇö still completed, scores still attached.
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


def test_get_evaluation_includes_bulk_operation(
    authenticated_client, db_session, org_id, seed_org, monkeypatch
):
    metric = _make_metric(db_session, org_id)
    call_import, _ = _make_call_import(db_session, org_id, rows=1)
    created = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json=_eval_body([metric.id]),
    ).json()

    monkeypatch.setattr(
        "app.services.call_imports.evaluation_bulk_op.get_evaluation_bulk_operation",
        lambda _evaluation_id: "abort",
    )

    detail = authenticated_client.get(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{created['id']}"
    )
    assert detail.status_code == 200
    assert detail.json()["bulk_operation"] == "abort"


def test_cancel_returns_409_when_bulk_operation_active(
    authenticated_client, db_session, org_id, seed_org, monkeypatch
):
    metric = _make_metric(db_session, org_id)
    call_import, _ = _make_call_import(db_session, org_id, rows=1)
    created = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json=_eval_body([metric.id]),
    ).json()

    _force_running(db_session, created["id"])

    monkeypatch.setattr(
        "app.services.call_imports.evaluation_bulk_op.get_evaluation_bulk_operation",
        lambda _evaluation_id: "retry",
    )
    monkeypatch.setattr(
        "app.services.call_imports.evaluation_bulk_op.try_set_evaluation_bulk_operation",
        lambda _evaluation_id, _operation: False,
    )

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{created['id']}/cancel"
    )
    assert response.status_code == 409
    assert "bulk retry operation" in response.json()["detail"]


def test_cancel_row_returns_409_when_bulk_operation_active(
    authenticated_client, db_session, org_id, seed_org, monkeypatch
):
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

    monkeypatch.setattr(
        "app.services.call_imports.evaluation_bulk_op.get_evaluation_bulk_operation",
        lambda _evaluation_id: "abort",
    )

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/"
        f"{created['id']}/rows/{eval_row.id}/cancel"
    )
    assert response.status_code == 409
    assert "bulk abort operation" in response.json()["detail"]


def _force_diarisation_running(
    db_session,
    evaluation_id,
    *,
    task_id_prefix="dia-task",
):
    """Set linked source rows to in-flight diarisation for cancel cascade tests."""
    eval_uuid = UUID(evaluation_id)
    eval_rows = (
        db_session.query(CallImportEvaluationRow)
        .filter(CallImportEvaluationRow.evaluation_id == eval_uuid)
        .all()
    )
    source_ids = [row.call_import_row_id for row in eval_rows]
    source_rows = (
        db_session.query(CallImportRow)
        .filter(CallImportRow.id.in_(source_ids))
        .all()
    )
    for idx, row in enumerate(source_rows):
        row.diarised_transcript_status = "running"
        row.celery_task_id = f"{task_id_prefix}-{idx}"
    db_session.commit()
    return source_rows


def test_cancel_evaluation_cascades_diarisation_on_source_rows(
    authenticated_client, db_session, org_id, seed_org, monkeypatch
):
    """Run-level abort should fail in-flight diarisation on linked source rows."""
    metric = _make_metric(db_session, org_id)
    call_import, _ = _make_call_import(db_session, org_id, rows=2)
    created = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json=_eval_body([metric.id]),
    ).json()

    _stub_celery_revoke(monkeypatch)
    _force_running(db_session, created["id"])
    source_rows = _force_diarisation_running(db_session, created["id"])

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{created['id']}/cancel"
    )
    assert response.status_code == 202, response.text

    db_session.expire_all()
    refreshed = (
        db_session.query(CallImportRow)
        .filter(CallImportRow.id.in_([row.id for row in source_rows]))
        .all()
    )
    assert {row.diarised_transcript_status for row in refreshed} == {"failed"}
    assert all(
        (row.diarised_transcript_error or "") == "Diarisation cancelled by user"
        for row in refreshed
    )
    assert all(row.celery_task_id is None for row in refreshed)


def test_cancel_evaluation_row_cascades_diarisation_on_source_row(
    authenticated_client, db_session, org_id, seed_org, monkeypatch
):
    """Row-level abort should fail in-flight diarisation on the linked source row."""
    metric = _make_metric(db_session, org_id)
    call_import, _ = _make_call_import(db_session, org_id, rows=2)
    created = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json=_eval_body([metric.id]),
    ).json()

    _stub_celery_revoke(monkeypatch)
    eval_rows = _force_running(db_session, created["id"])
    source_rows = _force_diarisation_running(db_session, created["id"])
    target = eval_rows[0]
    target_source = next(
        row for row in source_rows if row.id == target.call_import_row_id
    )
    sibling_source = next(
        row for row in source_rows if row.id != target.call_import_row_id
    )

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/"
        f"{created['id']}/rows/{target.id}/cancel"
    )
    assert response.status_code == 200, response.text

    db_session.expire_all()
    db_session.refresh(target_source)
    db_session.refresh(sibling_source)
    assert target_source.diarised_transcript_status == "failed"
    assert (
        target_source.diarised_transcript_error or ""
    ) == "Diarisation cancelled by user"
    assert target_source.celery_task_id is None
    assert sibling_source.diarised_transcript_status == "running"


def test_cancel_evaluation_sweeps_diarisation_when_eval_row_already_failed(
    authenticated_client, db_session, org_id, seed_org, monkeypatch,
):
    """Final sweep fails in-flight diarisation even if the eval row is already terminal."""
    metric = _make_metric(db_session, org_id)
    call_import, _ = _make_call_import(db_session, org_id, rows=1)
    created = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json=_eval_body([metric.id]),
    ).json()

    _stub_celery_revoke(monkeypatch)
    eval_row = (
        db_session.query(CallImportEvaluationRow)
        .filter(CallImportEvaluationRow.evaluation_id == UUID(created["id"]))
        .one()
    )
    source_row = db_session.get(CallImportRow, eval_row.call_import_row_id)
    eval_row.status = "failed"
    eval_row.error_message = "Evaluation cancelled by user"
    eval_row.celery_task_id = None
    source_row.diarised_transcript_status = "pending"
    source_row.celery_task_id = "dia-task-stale"
    db_session.commit()

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{created['id']}/cancel"
    )
    assert response.status_code == 202, response.text
    assert response.json()["target_count"] == 0

    db_session.expire_all()
    db_session.refresh(source_row)
    assert source_row.diarised_transcript_status == "failed"
    assert (
        source_row.diarised_transcript_error or ""
    ) == "Diarisation cancelled by user"
    assert source_row.celery_task_id is None


def test_retry_failed_rows_flips_partial_run_back_to_running(
    authenticated_client, db_session, org_id, seed_org
):
    """Retry on a partially-completed run should reset failed rows and resume."""
    metric = _make_metric(db_session, org_id)
    call_import, _rows = _make_call_import(db_session, org_id, rows=2)
    created = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json=_eval_body([metric.id]),
    ).json()

    eval_uuid = UUID(created["id"])
    eval_rows = (
        db_session.query(CallImportEvaluationRow)
        .filter(CallImportEvaluationRow.evaluation_id == eval_uuid)
        .order_by(CallImportEvaluationRow.created_at.asc())
        .all()
    )
    eval_rows[0].status = "completed"
    eval_rows[1].status = "failed"
    eval_rows[1].error_message = "LLM timeout"
    parent = (
        db_session.query(CallImportEvaluation)
        .filter(CallImportEvaluation.id == eval_uuid)
        .first()
    )
    parent.status = "partial"
    parent.completed_rows = 1
    parent.failed_rows = 1
    db_session.commit()

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{eval_uuid}/retry",
        json={},
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["requeued"] == 1

    db_session.refresh(parent)
    db_session.refresh(eval_rows[1])
    assert parent.status == "running"
    assert eval_rows[1].status == "pending"
    assert eval_rows[1].error_message is None


def test_retry_clears_failed_diarisation_to_idle_not_null(
    authenticated_client, db_session, org_id, seed_org
):
    """Retry must not NULL out diarised_transcript_status (NOT NULL column)."""
    metric = _make_metric(db_session, org_id)
    call_import, rows = _make_call_import(db_session, org_id, rows=1)
    created = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json=_eval_body([metric.id]),
    ).json()

    source_row = rows[0]
    source_row.recording_s3_key = "audio/org/test.mp3"
    source_row.diarised_transcript = None
    source_row.diarised_transcript_status = "failed"
    source_row.diarised_transcript_error = "STT timeout"

    eval_uuid = UUID(created["id"])
    eval_row = (
        db_session.query(CallImportEvaluationRow)
        .filter(CallImportEvaluationRow.evaluation_id == eval_uuid)
        .one()
    )
    eval_row.status = "failed"
    eval_row.error_message = "Diarisation failed"
    db_session.commit()

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{eval_uuid}/retry",
        json={},
    )
    assert response.status_code == 202, response.text

    db_session.refresh(source_row)
    assert source_row.diarised_transcript_status == "idle"
    assert source_row.diarised_transcript_error is None


def test_retry_marks_existing_diarised_transcript_completed(
    authenticated_client, db_session, org_id, seed_org
):
    """Eval-only retries should not force re-diarisation when a transcript exists."""
    metric = _make_metric(db_session, org_id)
    call_import, rows = _make_call_import(db_session, org_id, rows=1)
    created = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json=_eval_body([metric.id]),
    ).json()

    source_row = rows[0]
    source_row.recording_s3_key = "audio/org/test.mp3"
    source_row.diarised_transcript = "agent: hello\nuser: hi"
    source_row.diarised_transcript_status = "failed"

    eval_uuid = UUID(created["id"])
    eval_row = (
        db_session.query(CallImportEvaluationRow)
        .filter(CallImportEvaluationRow.evaluation_id == eval_uuid)
        .one()
    )
    eval_row.status = "failed"
    db_session.commit()

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{eval_uuid}/retry",
        json={},
    )
    assert response.status_code == 202, response.text

    db_session.refresh(source_row)
    assert source_row.diarised_transcript_status == "completed"
    assert "hello" in (source_row.diarised_transcript or "")


def test_evaluation_retry_can_override_telephony_credentials(
    authenticated_client, db_session, org_id, seed_org, monkeypatch
):
    """Retry should pin a new telephony integration on the batch when asked."""
    metric = _make_metric(db_session, org_id)
    wrong_integration = TelephonyIntegration(
        id=uuid4(),
        organization_id=org_id,
        provider="exotel",
        name="wrong",
        auth_id="enc-wrong",
        auth_token="enc-wrong",
        is_active=True,
    )
    right_integration = TelephonyIntegration(
        id=uuid4(),
        organization_id=org_id,
        provider="exotel",
        name="right",
        auth_id="enc-right",
        auth_token="enc-right",
        is_active=True,
        is_default=True,
    )
    db_session.add_all([wrong_integration, right_integration])
    db_session.commit()

    call_import, _rows = _make_call_import(
        db_session,
        org_id,
        rows=1,
        integration=wrong_integration,
    )
    created = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json=_eval_body([metric.id]),
    ).json()

    eval_uuid = UUID(created["id"])
    eval_row = (
        db_session.query(CallImportEvaluationRow)
        .filter(CallImportEvaluationRow.evaluation_id == eval_uuid)
        .first()
    )
    eval_row.status = "failed"
    eval_row.error_message = "import failed"
    db_session.commit()

    class _GoodClient:
        def test_connection(self):
            return None

    monkeypatch.setattr(
        "app.services.telephony.telephony_service.telephony_service.get_provider_client",
        lambda *_args, **_kwargs: _GoodClient(),
    )

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{eval_uuid}/retry",
        json={
            "provider": "exotel",
            "telephony_integration_id": str(right_integration.id),
        },
    )
    assert response.status_code == 202, response.text

    db_session.refresh(call_import)
    assert call_import.telephony_integration_id == right_integration.id
    assert call_import.provider == "exotel"


def test_evaluation_retry_rejects_invalid_telephony_credentials(
    authenticated_client, db_session, org_id, seed_org, monkeypatch
):
    metric = _make_metric(db_session, org_id)
    integration = TelephonyIntegration(
        id=uuid4(),
        organization_id=org_id,
        provider="exotel",
        name="bad",
        auth_id="enc-bad",
        auth_token="enc-bad",
        is_active=True,
        is_default=True,
    )
    db_session.add(integration)
    db_session.commit()

    call_import, _rows = _make_call_import(
        db_session,
        org_id,
        rows=1,
        integration=integration,
    )
    created = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json=_eval_body([metric.id]),
    ).json()
    eval_uuid = UUID(created["id"])
    eval_row = (
        db_session.query(CallImportEvaluationRow)
        .filter(CallImportEvaluationRow.evaluation_id == eval_uuid)
        .first()
    )
    eval_row.status = "failed"
    db_session.commit()

    class _BadClient:
        def test_connection(self):
            raise ValueError("Exotel auth failed (HTTP 401): bad token")

    monkeypatch.setattr(
        "app.services.telephony.telephony_service.telephony_service.get_provider_client",
        lambda *_args, **_kwargs: _BadClient(),
    )

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{eval_uuid}/retry",
        json={
            "provider": "exotel",
            "telephony_integration_id": str(integration.id),
        },
    )
    assert response.status_code == 400
    assert "credentials could not be verified" in response.json()["detail"].lower()
def test_create_evaluation_sets_actor_emails(
    authenticated_client, db_session, org_id, seed_org
):
    metric = _make_metric(db_session, org_id)
    call_import, _rows = _make_call_import(db_session, org_id, rows=2)

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json=_eval_body([metric.id]),
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["created_by_email"] == "owner@example.com"
    assert body["last_updated_by_email"] == "owner@example.com"


def test_update_evaluation_name_stamps_last_updated_by_email(
    authenticated_client, db_session, org_id, seed_org
):
    metric = _make_metric(db_session, org_id)
    call_import, _rows = _make_call_import(db_session, org_id, rows=1)

    created = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json=_eval_body([metric.id]),
    )
    assert created.status_code == 202, created.text
    eval_id = created.json()["id"]

    patched = authenticated_client.patch(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{eval_id}",
        json={"name": "Renamed run"},
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["name"] == "Renamed run"
    assert body["created_by_email"] == "owner@example.com"
    assert body["last_updated_by_email"] == "owner@example.com"
