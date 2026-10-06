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
    )

    assert result["success"] is True
    assert captured["url"].endswith("/v2/enqueue")
    assert captured["json"]["routing_key"] == "routing-key-abc"
    assert captured["json"]["payload"]["severity"] in ("critical", "warning", "error")
