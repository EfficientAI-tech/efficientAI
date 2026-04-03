"""Tests for alert notification service helper behavior."""

from datetime import datetime, UTC
from types import SimpleNamespace

from app.services.alerts.alert_notification_service import AlertNotificationService


def test_severity_label_and_webhook_mask_helpers():
    service = AlertNotificationService()
    assert service._get_severity_label(">", 10, 25) == "CRITICAL"
    assert service._get_severity_label(">", 10, 12) == "ALERT"

    masked = service._mask_webhook_url("https://hooks.slack.com/services/T000/B000/verylongtoken")
    assert "..." in masked


def test_send_all_notifications_dispatches_to_all_channels(monkeypatch):
    service = AlertNotificationService()

    monkeypatch.setattr(
        service,
        "send_slack_notification",
        lambda **_kwargs: {"success": True, "channel": "slack_webhook"},
    )
    monkeypatch.setattr(
        service,
        "send_email_notification",
        lambda **_kwargs: {"success": False, "channel": "email"},
    )

    alert = SimpleNamespace(
        id="alert-1",
        name="High error",
        description="desc",
        metric_type="error_rate",
        aggregation="avg",
        operator=">",
        threshold_value=5.0,
        time_window_minutes=60,
        notify_webhooks=["https://hooks.slack.com/services/T/A/B"],
        notify_emails=["a@example.com", "b@example.com"],
    )

    results = service.send_all_notifications(
        alert=alert,
        triggered_value=7.0,
        triggered_at=datetime.now(UTC),
        agent_names=["Agent A"],
        history_id="history-1",
    )

    assert len(results) == 3
    assert sum(1 for r in results if r["success"]) == 1
