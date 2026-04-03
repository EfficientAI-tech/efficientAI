"""API tests for alerts routes."""


def test_create_list_get_update_toggle_delete_alert(authenticated_client):
    payload = {
        "name": "High Call Volume",
        "description": "Alert on call spikes",
        "metric_type": "number_of_calls",
        "aggregation": "sum",
        "operator": ">",
        "threshold_value": 100,
        "time_window_minutes": 60,
        "notify_frequency": "immediate",
    }
    create_response = authenticated_client.post("/api/v1/alerts", json=payload)
    assert create_response.status_code == 201
    alert_id = create_response.json()["id"]

    list_response = authenticated_client.get("/api/v1/alerts")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    get_response = authenticated_client.get(f"/api/v1/alerts/{alert_id}")
    assert get_response.status_code == 200

    update_response = authenticated_client.put(
        f"/api/v1/alerts/{alert_id}",
        json={"threshold_value": 120, "description": "Updated desc"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["threshold_value"] == 120

    toggle_response = authenticated_client.post(f"/api/v1/alerts/{alert_id}/toggle")
    assert toggle_response.status_code == 200
    assert toggle_response.json()["status"] == "paused"

    delete_response = authenticated_client.delete(f"/api/v1/alerts/{alert_id}")
    assert delete_response.status_code == 204


def test_trigger_evaluate_all_and_test_notification(authenticated_client, monkeypatch, make_alert):
    from app.api.v1.routes import alerts as alerts_routes

    alert = make_alert(notify_webhooks=["https://hooks.slack.com/services/abc"])

    monkeypatch.setattr(
        alerts_routes.alert_evaluation_service,
        "evaluate_single_alert",
        lambda *_args, **_kwargs: {
            "alert_id": str(alert.id),
            "alert_name": alert.name,
            "triggered": True,
            "metric_value": 150.0,
            "threshold": 100.0,
        },
    )
    monkeypatch.setattr(
        alerts_routes.alert_notification_service,
        "send_slack_notification",
        lambda **_kwargs: {"success": True, "channel": "slack"},
    )

    trigger_response = authenticated_client.post(f"/api/v1/alerts/{alert.id}/trigger")
    assert trigger_response.status_code == 200
    assert trigger_response.json()["triggered"] is True

    evaluate_all_response = authenticated_client.post("/api/v1/alerts/evaluate/all")
    assert evaluate_all_response.status_code == 200
    assert evaluate_all_response.json()["total_alerts"] == 1
    assert evaluate_all_response.json()["triggered"] == 1

    test_notification_response = authenticated_client.post(
        f"/api/v1/alerts/{alert.id}/test-notification",
        json={},
    )
    assert test_notification_response.status_code == 200
    assert test_notification_response.json()["successful"] == 1


def test_list_alert_history_empty(authenticated_client):
    response = authenticated_client.get("/api/v1/alerts/history/all")
    assert response.status_code == 200
    assert response.json() == []
