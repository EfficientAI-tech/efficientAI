"""Row selection for metric-cluster generation."""

from __future__ import annotations

from datetime import datetime, timezone

from app.models.database import CallImportEvaluation
from tests.test_api.test_call_import_evaluation_insights import _seed_eval_with_data


def test_list_eligible_metric_cluster_rows_empty_scores(
    authenticated_client, db_session, org_id, seed_org, make_ai_provider
):
    make_ai_provider(provider="openai", is_active=True)
    call_import, evaluation, _ = _seed_eval_with_data(db_session, org_id)

    response = authenticated_client.get(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/metric-clusters/eligible-rows",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["items"] == []


def test_generate_metric_clusters_rejects_unknown_row_id(
    authenticated_client, db_session, org_id, seed_org, make_ai_provider
):
    make_ai_provider(provider="openai", is_active=True)
    call_import, evaluation, _ = _seed_eval_with_data(db_session, org_id)

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/metric-clusters",
        json={"evaluation_row_ids": ["00000000-0000-0000-0000-000000000099"]},
    )
    assert response.status_code == 400
    assert "evaluation_row_ids" in response.json()["detail"].lower() or "missing" in response.json()["detail"].lower()


def test_cancel_preserves_selected_row_ids_in_state(
    authenticated_client, db_session, org_id, seed_org, make_ai_provider, monkeypatch
):
    make_ai_provider(provider="openai", is_active=True)
    call_import, evaluation, _ = _seed_eval_with_data(db_session, org_id)

    evaluation.metric_clusters = {
        "status": "running",
        "celery_task_id": "task-1",
        "selected_evaluation_row_ids": ["row-a", "row-b"],
        "progress": {"completed_llm_calls": 1, "total_llm_calls": 10},
    }
    db_session.commit()

    class _Control:
        @staticmethod
        def revoke(*_a, **_k):
            return None

    monkeypatch.setattr(
        "app.workers.celery_app.celery_app",
        type("C", (), {"control": _Control})(),
    )

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/metric-clusters/cancel",
    )
    assert response.status_code == 200
    assert response.json()["selected_evaluation_row_ids"] == ["row-a", "row-b"]
