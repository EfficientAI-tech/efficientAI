"""Tests for alert evaluation service orchestration behavior."""

from types import SimpleNamespace
from uuid import uuid4

from app.services.alerts.alert_evaluation_service import AlertEvaluationService


def _sample_alert():
    return SimpleNamespace(
        id=uuid4(),
        name="High error rate",
        operator=">",
        threshold_value=5.0,
        notify_frequency="immediate",
    )


def test_evaluate_single_alert_skips_when_in_cooldown(monkeypatch):
    service = AlertEvaluationService()
    alert = _sample_alert()
    monkeypatch.setattr(service, "_should_notify", lambda *_args, **_kwargs: False)

    result = service.evaluate_single_alert(alert=alert, db=object())

    assert result["triggered"] is False
    assert result["skipped_cooldown"] is True


def test_evaluate_single_alert_handles_unknown_operator(monkeypatch):
    service = AlertEvaluationService()
    alert = _sample_alert()
    alert.operator = "??"
    monkeypatch.setattr(service, "_should_notify", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(service, "_compute_metric", lambda *_args, **_kwargs: 10.0)

    result = service.evaluate_single_alert(alert=alert, db=object())

    assert result["triggered"] is False
    assert "Unknown operator" in result["error"]


def test_evaluate_single_alert_triggers_when_condition_matches(monkeypatch):
    service = AlertEvaluationService()
    alert = _sample_alert()
    monkeypatch.setattr(service, "_should_notify", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(service, "_compute_metric", lambda *_args, **_kwargs: 12.0)
    monkeypatch.setattr(
        service,
        "_trigger_alert",
        lambda alert, triggered_value, db: {
            "alert_id": str(alert.id),
            "triggered": True,
            "metric_value": triggered_value,
        },
    )

    result = service.evaluate_single_alert(alert=alert, db=object())
    assert result["triggered"] is True
    assert result["metric_value"] == 12.0
