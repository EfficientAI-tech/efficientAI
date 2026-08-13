"""API tests for Metrics Studio."""

from uuid import uuid4


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
