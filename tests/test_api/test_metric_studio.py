"""API tests for Metrics Studio."""

from datetime import datetime, timezone
from uuid import uuid4

from app.models.database import MetricStudioRun, MetricStudioRunResult


def test_create_and_list_metric_draft(authenticated_client):
    payload = {
        "name": "Studio Draft Metric",
        "description": "Test draft rubric",
        "metric_type": "rating",
        "trigger": "always",
        "metric_origin": "custom",
        "studio_notes": "experiment v1",
    }
    create_response = authenticated_client.post("/api/v1/metrics/drafts", json=payload)
    assert create_response.status_code == 201
    body = create_response.json()
    assert body["lifecycle"] == "draft"
    assert body["enabled"] is False

    list_active = authenticated_client.get("/api/v1/metrics")
    assert list_active.status_code == 200
    assert all(m.get("lifecycle", "active") != "draft" for m in list_active.json())

    list_drafts = authenticated_client.get(
        "/api/v1/metrics", params={"drafts_only": True}
    )
    assert list_drafts.status_code == 200
    assert any(m["id"] == body["id"] for m in list_drafts.json())


def test_promote_metric_draft(authenticated_client):
    create_response = authenticated_client.post(
        "/api/v1/metrics/drafts",
        json={
            "name": f"Promote Me {uuid4().hex[:6]}",
            "description": "Draft to promote",
            "metric_type": "boolean",
            "trigger": "always",
        },
    )
    assert create_response.status_code == 201
    metric_id = create_response.json()["id"]

    promote_response = authenticated_client.post(
        f"/api/v1/metrics/{metric_id}/promote"
    )
    assert promote_response.status_code == 200
    promoted = promote_response.json()
    assert promoted["metric"]["lifecycle"] == "active"
    assert promoted["metric"]["enabled"] is True
    assert promoted["promoted_at"]


def test_list_metrics_enabled_only_excludes_disabled(authenticated_client, make_metric):
    enabled = make_metric(name="Studio Enabled Metric", enabled=True)
    disabled = make_metric(name="Studio Disabled Metric", enabled=False)

    all_response = authenticated_client.get("/api/v1/metrics")
    assert all_response.status_code == 200
    all_ids = {m["id"] for m in all_response.json()}
    assert str(enabled.id) in all_ids
    assert str(disabled.id) in all_ids

    enabled_only_response = authenticated_client.get(
        "/api/v1/metrics",
        params={"enabled_only": True},
    )
    assert enabled_only_response.status_code == 200
    enabled_ids = {m["id"] for m in enabled_only_response.json()}
    assert str(enabled.id) in enabled_ids
    assert str(disabled.id) not in enabled_ids


def test_create_metric_studio_run_requires_sources(authenticated_client, make_metric):
    metric = make_metric(name="Studio Run Metric", metric_type="rating")
    response = authenticated_client.post(
        "/api/v1/metric-studio/runs",
        json={
            "metric_ids": [str(metric.id)],
            "sources": [],
        },
    )
    assert response.status_code == 422


def test_list_metric_studio_run_results_pagination_stable_when_created_at_ties(
    authenticated_client,
    db_session,
    org_id,
    default_workspace,
):
    """Bulk insert gives identical created_at; id tie-breaker keeps pages disjoint."""
    run_id = uuid4()
    shared_created_at = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    run = MetricStudioRun(
        id=run_id,
        organization_id=org_id,
        workspace_id=default_workspace.id,
        selected_metric_ids=["00000000-0000-0000-0000-000000000001"],
        status="completed",
        total_items=5,
        created_at=shared_created_at,
    )
    db_session.add(run)
    result_ids = sorted(uuid4() for _ in range(5))
    for idx, result_id in enumerate(result_ids):
        db_session.add(
            MetricStudioRunResult(
                id=result_id,
                run_id=run_id,
                workspace_id=default_workspace.id,
                source_kind="call_recording",
                source_ref=f"recording-{idx}",
                display_label=f"Row {idx}",
                status="completed",
                metric_scores={},
                created_at=shared_created_at,
            )
        )
    db_session.commit()

    page_size = 2
    seen: list[str] = []
    for skip in range(0, 5, page_size):
        response = authenticated_client.get(
            f"/api/v1/metric-studio/runs/{run_id}/results",
            params={"skip": skip, "limit": page_size},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 5
        seen.extend(item["id"] for item in body["items"])

    assert len(seen) == len(set(seen)) == 5
    assert seen == [str(rid) for rid in sorted(result_ids)]
