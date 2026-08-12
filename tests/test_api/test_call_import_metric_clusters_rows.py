"""Row selection for metric-cluster generation."""

from __future__ import annotations

import types

from tests.test_api.test_call_import_evaluation_insights import _seed_eval_with_data
from tests.test_api.test_call_import_evaluation_rows_sorting import _seed_eval_with_rows
from tests.test_api.test_call_import_evaluations import _stub_celery_revoke


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


def test_list_eligible_metric_cluster_rows_count_only(
    authenticated_client, db_session, org_id, seed_org, make_ai_provider
):
    make_ai_provider(provider="openai", is_active=True)
    call_import, evaluation, _ = _seed_eval_with_rows(
        db_session,
        org_id,
        rows=[
            {"conversation_id": f"c{i}", "status": "completed", "score_value": 0.2}
            for i in range(5)
        ],
    )

    response = authenticated_client.get(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/metric-clusters/eligible-rows",
        params={"count_only": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert body["items"] == []


def test_list_eligible_metric_cluster_rows_limit(
    authenticated_client, db_session, org_id, seed_org, make_ai_provider
):
    make_ai_provider(provider="openai", is_active=True)
    call_import, evaluation, _ = _seed_eval_with_rows(
        db_session,
        org_id,
        rows=[
            {"conversation_id": f"c{i}", "status": "completed", "score_value": 0.2}
            for i in range(5)
        ],
    )

    response = authenticated_client.get(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/metric-clusters/eligible-rows",
        params={"limit": 2},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2


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


def test_generate_metric_clusters_rejects_row_limit_with_row_ids(
    authenticated_client, db_session, org_id, seed_org, make_ai_provider
):
    make_ai_provider(provider="openai", is_active=True)
    call_import, evaluation, _ = _seed_eval_with_rows(
        db_session,
        org_id,
        rows=[
            {"conversation_id": "c0", "status": "completed", "score_value": 0.2},
        ],
    )

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/metric-clusters",
        json={
            "row_limit": 1,
            "evaluation_row_ids": ["00000000-0000-0000-0000-000000000001"],
        },
    )
    assert response.status_code == 400
    assert "row_limit" in response.json()["detail"].lower()


def test_generate_metric_clusters_row_limit(
    authenticated_client,
    db_session,
    org_id,
    seed_org,
    make_ai_provider,
    monkeypatch,
):
    make_ai_provider(provider="openai", is_active=True)
    call_import, evaluation, _ = _seed_eval_with_rows(
        db_session,
        org_id,
        rows=[
            {"conversation_id": f"c{i}", "status": "completed", "score_value": 0.2}
            for i in range(5)
        ],
    )

    captured: dict = {}

    def fake_apply_async(*, kwargs=None, **_kw):
        captured.update(kwargs or {})
        return types.SimpleNamespace(id="cluster-task-1")

    monkeypatch.setattr(
        "app.workers.tasks.generate_evaluation_metric_clusters.generate_evaluation_metric_clusters_task.apply_async",
        fake_apply_async,
    )

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/metric-clusters",
        json={"row_limit": 2},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "running"
    assert len(body["selected_evaluation_row_ids"]) == 2
    assert len(captured["evaluation_row_ids"]) == 2


def test_generate_metric_clusters_stamps_last_updated_by_email(
    authenticated_client,
    db_session,
    org_id,
    seed_org,
    make_ai_provider,
    monkeypatch,
):
    make_ai_provider(provider="openai", is_active=True)
    call_import, evaluation, _ = _seed_eval_with_rows(
        db_session,
        org_id,
        rows=[
            {"conversation_id": "c0", "status": "completed", "score_value": 0.2},
        ],
    )
    evaluation.last_updated_by_user_id = None
    db_session.commit()

    def fake_apply_async(*, kwargs=None, **_kw):
        return types.SimpleNamespace(id="cluster-task-1")

    monkeypatch.setattr(
        "app.workers.tasks.generate_evaluation_metric_clusters.generate_evaluation_metric_clusters_task.apply_async",
        fake_apply_async,
    )

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/metric-clusters",
        json={"row_limit": 1},
    )
    assert response.status_code == 200, response.text

    detail = authenticated_client.get(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}"
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["last_updated_by_email"] == "owner@example.com"


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

    _stub_celery_revoke(monkeypatch)

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/metric-clusters/cancel",
    )
    assert response.status_code == 200
    assert response.json()["selected_evaluation_row_ids"] == ["row-a", "row-b"]
