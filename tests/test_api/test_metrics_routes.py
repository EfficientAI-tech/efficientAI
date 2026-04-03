"""API tests for metrics routes."""


def test_create_and_list_metrics(authenticated_client):
    payload = {
        "name": "Resolution Quality",
        "description": "Checks if the issue was resolved",
        "metric_type": "rating",
        "trigger": "always",
        "enabled": True,
    }
    create_response = authenticated_client.post("/api/v1/metrics", json=payload)

    assert create_response.status_code == 201
    assert create_response.json()["name"] == "Resolution Quality"

    list_response = authenticated_client.get("/api/v1/metrics")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1


def test_update_metric(authenticated_client, make_metric):
    metric = make_metric(name="Old Name", metric_type="number")

    response = authenticated_client.put(
        f"/api/v1/metrics/{metric.id}",
        json={"name": "New Name", "enabled": False},
    )

    assert response.status_code == 200
    assert response.json()["name"] == "New Name"
    assert response.json()["enabled"] is False


def test_delete_metric(authenticated_client, make_metric):
    metric = make_metric(name="Delete Me")

    response = authenticated_client.delete(f"/api/v1/metrics/{metric.id}")

    assert response.status_code == 204
