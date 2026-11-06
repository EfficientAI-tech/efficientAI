"""API tests for user-insights cancel."""

from __future__ import annotations

from datetime import datetime, timezone

from app.models.database import CallImportEvaluation
from tests.test_api.test_call_import_evaluation_insights import _seed_eval_with_data
from tests.test_api.test_call_import_evaluations import _stub_celery_revoke


def test_cancel_running_user_insights(
    authenticated_client, db_session, org_id, seed_org, make_ai_provider, monkeypatch
):
    make_ai_provider(provider="openai", is_active=True)
    call_import, evaluation, _ = _seed_eval_with_data(db_session, org_id)

    evaluation.user_insights = {
        "status": "running",
        "celery_task_id": "insights-task-abc",
        "progress": {"completed_batches": 1, "total_batches": 3},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    db_session.commit()

    revoke = _stub_celery_revoke(monkeypatch)

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/user-insights/cancel",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled"

    revoke.assert_called_once_with(["insights-task-abc"], terminate=False)

    refreshed = (
        db_session.query(CallImportEvaluation)
        .filter(CallImportEvaluation.id == evaluation.id)
        .first()
    )
    assert refreshed.user_insights["status"] == "cancelled"
    assert refreshed.user_insights.get("celery_task_id") is None


def test_cancel_user_insights_idempotent_when_not_running(
    authenticated_client, db_session, org_id, seed_org, make_ai_provider
):
    make_ai_provider(provider="openai", is_active=True)
    call_import, evaluation, _ = _seed_eval_with_data(db_session, org_id)

    evaluation.user_insights = {
        "status": "completed",
        "insights": [],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    db_session.commit()

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/user-insights/cancel",
    )
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
