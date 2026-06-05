"""Cancel endpoint for in-flight metric-cluster generation."""

from __future__ import annotations

from datetime import datetime, timezone

from app.models.database import CallImportEvaluation
from tests.test_api.test_call_import_evaluation_insights import _seed_eval_with_data


def test_cancel_running_metric_clusters(
    authenticated_client, db_session, org_id, seed_org, make_ai_provider, monkeypatch
):
    make_ai_provider(provider="openai", is_active=True)
    call_import, evaluation, _ = _seed_eval_with_data(db_session, org_id)

    evaluation.metric_clusters = {
        "status": "running",
        "celery_task_id": "clusters-task-abc",
        "progress": {"completed_llm_calls": 10, "total_llm_calls": 352},
        "provider": "openai",
        "model": "gpt-4.1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    db_session.commit()

    revoked: list[tuple] = []

    class _Control:
        @staticmethod
        def revoke(task_id, *, terminate=False, signal=None):
            revoked.append((task_id, terminate, signal))

    class _CeleryApp:
        control = _Control()

    monkeypatch.setattr(
        "app.workers.celery_app.celery_app",
        _CeleryApp(),
    )

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/metric-clusters/cancel",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled"
    assert "cancelled by user" in (body.get("error_message") or "").lower()
    assert body["progress"]["completed_llm_calls"] == 10
    assert body["progress"]["total_llm_calls"] == 352

    assert revoked == [("clusters-task-abc", True, "SIGTERM")]

    refreshed = (
        db_session.query(CallImportEvaluation)
        .filter(CallImportEvaluation.id == evaluation.id)
        .first()
    )
    assert refreshed.metric_clusters["status"] == "cancelled"
    assert refreshed.metric_clusters.get("celery_task_id") is None


def test_cancel_metric_clusters_idempotent_when_not_running(
    authenticated_client, db_session, org_id, seed_org, make_ai_provider
):
    make_ai_provider(provider="openai", is_active=True)
    call_import, evaluation, _ = _seed_eval_with_data(db_session, org_id)

    evaluation.metric_clusters = {
        "status": "completed",
        "groups": [],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    db_session.commit()

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/metric-clusters/cancel",
    )
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
