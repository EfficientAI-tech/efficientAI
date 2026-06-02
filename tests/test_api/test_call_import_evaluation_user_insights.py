"""API tests for LLM-generated user insights endpoints."""

from __future__ import annotations

import sys
import types
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.models.database import (
    CallImport,
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
    Metric,
    Workspace,
)
from app.models.enums import CallImportRowStatus, CallImportStatus


@pytest.fixture(autouse=True)
def stub_user_insights_worker(monkeypatch):
    calls: list[dict] = []

    fake_module = types.ModuleType(
        "app.workers.tasks.generate_evaluation_user_insights"
    )

    class _Task:
        @staticmethod
        def delay(evaluation_id, *, provider=None, model=None, max_llm_calls=None):
            calls.append(
                {
                    "evaluation_id": evaluation_id,
                    "provider": provider,
                    "model": model,
                    "max_llm_calls": max_llm_calls,
                }
            )
            return types.SimpleNamespace(id="user-insights-task")

    fake_module.generate_evaluation_user_insights_task = _Task()
    monkeypatch.setitem(
        sys.modules,
        "app.workers.tasks.generate_evaluation_user_insights",
        fake_module,
    )
    return calls


def _ensure_default_workspace(db_session, org_id) -> Workspace:
    ws = (
        db_session.query(Workspace)
        .filter(Workspace.organization_id == org_id, Workspace.is_default.is_(True))
        .first()
    )
    if ws is None:
        ws = Workspace(
            organization_id=org_id,
            name="Default",
            slug="default",
            is_default=True,
        )
        db_session.add(ws)
        db_session.commit()
        db_session.refresh(ws)
    return ws


def _seed_evaluation(db_session, org_id):
    workspace = _ensure_default_workspace(db_session, org_id)
    metric = Metric(
        organization_id=org_id,
        workspace_id=workspace.id,
        name="Politeness",
        metric_type="rating",
        enabled=True,
        supported_surfaces=["call_imports"],
        enabled_surfaces=["call_imports"],
    )
    call_import = CallImport(
        organization_id=org_id,
        workspace_id=workspace.id,
        provider=None,
        original_filename="batch.csv",
        total_rows=1,
        completed_rows=1,
        failed_rows=0,
        status=CallImportStatus.COMPLETED,
    )
    db_session.add_all([metric, call_import])
    db_session.flush()

    source_row = CallImportRow(
        call_import_id=call_import.id,
        organization_id=org_id,
        row_index=0,
        conversation_id="ext-0",
        transcript="hello",
        diarised_transcript="user: hello",
        status=CallImportRowStatus.COMPLETED,
    )
    evaluation = CallImportEvaluation(
        call_import_id=call_import.id,
        organization_id=org_id,
        workspace_id=workspace.id,
        selected_metric_ids=[str(metric.id)],
        status="completed",
        total_rows=1,
        completed_rows=1,
        failed_rows=0,
    )
    db_session.add_all([source_row, evaluation])
    db_session.flush()
    db_session.add(
        CallImportEvaluationRow(
            evaluation_id=evaluation.id,
            call_import_row_id=source_row.id,
            status="completed",
            metric_scores={
                str(metric.id): {"value": 4, "rationale": "Polite exchange."}
            },
        )
    )
    db_session.commit()
    return call_import, evaluation


def test_get_user_insights_returns_null_when_missing(
    authenticated_client, db_session, org_id, seed_org
):
    call_import, evaluation = _seed_evaluation(db_session, org_id)
    response = authenticated_client.get(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/user-insights"
    )
    assert response.status_code == 200
    assert response.json() is None


def test_get_user_insights_returns_cached_state(
    authenticated_client, db_session, org_id, seed_org
):
    call_import, evaluation = _seed_evaluation(db_session, org_id)
    evaluation.user_insights = {
        "status": "completed",
        "insights": [
            {
                "id": "insight-1",
                "title": "Caller Context",
                "categories": [{"label": "New issue", "count": 5, "share_pct": 50.0}],
                "observation": "Half of callers report new issues.",
                "evidence": {"quote": "My geyser is broken", "conversation_id": "ext-0"},
            }
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_at_completed_rows": 1,
        "llm_calls_used": 3,
    }
    db_session.commit()

    response = authenticated_client.get(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/user-insights"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert len(body["insights"]) == 1
    assert body["insights"][0]["title"] == "Caller Context"


def test_post_user_insights_enqueues_task(
    authenticated_client,
    db_session,
    org_id,
    seed_org,
    make_ai_provider,
    stub_user_insights_worker,
):
    make_ai_provider(provider="openai", is_active=True)
    call_import, evaluation = _seed_evaluation(db_session, org_id)
    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/user-insights",
        json={"regenerate": True, "force": True, "max_llm_calls": 100},
    )
    assert response.status_code == 200
    assert len(stub_user_insights_worker) == 1
    assert stub_user_insights_worker[0]["evaluation_id"] == str(evaluation.id)
    assert stub_user_insights_worker[0]["max_llm_calls"] == 100
    assert response.json()["max_llm_calls"] == 100


def test_post_user_insights_requires_completed_rows(
    authenticated_client, db_session, org_id, seed_org
):
    workspace = _ensure_default_workspace(db_session, org_id)
    call_import = CallImport(
        organization_id=org_id,
        workspace_id=workspace.id,
        provider=None,
        original_filename="batch.csv",
        total_rows=0,
        completed_rows=0,
        failed_rows=0,
        status=CallImportStatus.COMPLETED,
    )
    db_session.add(call_import)
    db_session.flush()
    evaluation = CallImportEvaluation(
        call_import_id=call_import.id,
        organization_id=org_id,
        workspace_id=workspace.id,
        selected_metric_ids=[],
        status="pending",
        total_rows=0,
        completed_rows=0,
        failed_rows=0,
    )
    db_session.add(evaluation)
    db_session.commit()

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/user-insights",
        json={},
    )
    assert response.status_code == 400
