"""PagerDuty and Slack notification payload tests."""

from datetime import datetime, UTC

from app.services.alerts.alert_notification_service import AlertNotificationService


def test_slack_notification_includes_blocks(monkeypatch):
    service = AlertNotificationService()
    captured = {}

    class FakeResponse:
        status_code = 200
        text = "ok"

    def fake_post(url, json=None):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr(
        "httpx.Client",
        lambda *args, **kwargs: type(
            "C",
            (),
            {
                "__enter__": lambda self: self,
                "__exit__": lambda *a: None,
                "post": staticmethod(fake_post),
            },
        )(),
    )

    result = service.send_slack_notification(
        webhook_url="https://hooks.slack.com/services/T/B/X",
        alert_name="High errors",
        alert_description=None,
        metric_type="error_rate",
        aggregation="avg",
        operator=">",
        threshold_value=5.0,
        triggered_value=12.0,
        time_window_minutes=30,
        triggered_at=datetime.now(UTC),
    )

    assert result["success"] is True
    assert captured["json"]["blocks"][0]["type"] == "header"


def test_pagerduty_notification_success(monkeypatch):
    service = AlertNotificationService()
    captured = {}

    class FakeResponse:
        status_code = 202
        text = "Accepted"

    def fake_post(url, json=None):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr(
        "httpx.Client",
        lambda *args, **kwargs: type(
            "C",
            (),
            {
                "__enter__": lambda self: self,
                "__exit__": lambda *a: None,
                "post": staticmethod(fake_post),
            },
        )(),
    )

    result = service.send_pagerduty_notification(
        routing_key="routing-key-abc",
        alert_name="Latency",
        alert_description="desc",
        metric_type="latency",
        aggregation="max",
        operator=">",
        threshold_value=100.0,
        triggered_value=250.0,
        time_window_minutes=15,
        triggered_at=datetime.now(UTC),
        alert_id="alert-uuid",
        history_id="hist-uuid",
    )

    assert result["success"] is True
    assert captured["url"].endswith("/v2/enqueue")
    assert captured["json"]["routing_key"] == "routing-key-abc"
    assert captured["json"]["dedup_key"] == "efficientai-incident-hist-uuid"
    assert captured["json"]["payload"]["severity"] in ("critical", "warning", "error")


def test_pagerduty_acknowledge_success(monkeypatch):
    service = AlertNotificationService()
    captured = {}

    class FakeResponse:
        status_code = 202
        text = "Accepted"

    def fake_post(url, json=None):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr(
        "httpx.Client",
        lambda *args, **kwargs: type(
            "C",
            (),
            {
                "__enter__": lambda self: self,
                "__exit__": lambda *a: None,
                "post": staticmethod(fake_post),
            },
        )(),
    )

    result = service.send_pagerduty_acknowledge(
        routing_key="routing-key-abc",
        alert_name="Latency",
        history_id="hist-uuid",
        alert_id="alert-uuid",
        acknowledged_by="oncall@example.com",
    )

    assert result["success"] is True
    assert captured["json"]["event_action"] == "acknowledge"
    assert captured["json"]["dedup_key"] == "efficientai-incident-hist-uuid"
    assert "oncall@example.com" in captured["json"]["payload"]["summary"]


def test_send_acknowledge_notifications_routing_keys(monkeypatch):
    service = AlertNotificationService()
    calls = []

    def fake_ack(self, routing_key, alert_name, **kwargs):
        calls.append(routing_key)
        return {"success": True, "channel": "pagerduty_acknowledge"}

    monkeypatch.setattr(
        AlertNotificationService,
        "send_pagerduty_acknowledge",
        fake_ack,
    )

    class FakeAlert:
        id = "a1"
        name = "Test"
        notify_pagerduty_routing_keys = ["key-one", "  ", "key-two"]

    results = service.send_acknowledge_notifications(
        FakeAlert(),
        history_id="h1",
        acknowledged_by="user@test.com",
    )

    assert len(results) == 2
    assert calls == ["key-one", "key-two"]
