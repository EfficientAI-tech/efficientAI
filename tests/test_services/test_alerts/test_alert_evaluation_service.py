"""Tests for alert evaluation service orchestration behavior."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.services.alerts.alert_evaluation_service import AlertEvaluationService


def _fake_db_for_alert(alert):
    class FakeQuery:
        def filter(self, *_a, **_k):
            return self

        def with_for_update(self):
            return self

        def first(self):
            return alert

    class FakeDb:
        def query(self, _model):
            return FakeQuery()

    return FakeDb()


def _sample_alert():
    return SimpleNamespace(
        id=uuid4(),
        name="High error rate",
        operator=">",
        threshold_value=5.0,
        notify_frequency="immediate",
        metric_type="error_rate",
        aggregation="avg",
        time_window_minutes=60,
        organization_id=uuid4(),
        agent_ids=None,
    )


def test_evaluate_single_alert_uses_ongoing_incident_when_open(monkeypatch):
    service = AlertEvaluationService()
    alert = _sample_alert()
    monkeypatch.setattr(service, "_compute_metric", lambda *_args, **_kwargs: 12.0)
    monkeypatch.setattr(
        service,
        "_get_open_incidents",
        lambda *_args, **_kwargs: [object()],
    )
    monkeypatch.setattr(
        service,
        "_handle_ongoing_incident",
        lambda **_kwargs: {
            "alert_id": str(alert.id),
            "triggered": True,
            "ongoing_incident": True,
            "new_incident": False,
            "metric_value": 12.0,
            "skipped_cooldown": True,
            "history_id": "hist-1",
        },
    )

    result = service.evaluate_single_alert(alert=alert, db=_fake_db_for_alert(alert))

    assert result["triggered"] is True
    assert result["ongoing_incident"] is True
    assert result["skipped_cooldown"] is True


def test_evaluate_single_alert_handles_unknown_operator(monkeypatch):
    service = AlertEvaluationService()
    alert = _sample_alert()
    alert.operator = "??"
    monkeypatch.setattr(service, "_compute_metric", lambda *_args, **_kwargs: 10.0)

    result = service.evaluate_single_alert(alert=alert, db=_fake_db_for_alert(alert))

    assert result["triggered"] is False
    assert "Unknown operator" in result["error"]


def test_evaluate_single_alert_triggers_when_condition_matches(monkeypatch):
    service = AlertEvaluationService()
    alert = _sample_alert()
    monkeypatch.setattr(service, "_compute_metric", lambda *_args, **_kwargs: 12.0)
    monkeypatch.setattr(service, "_get_open_incidents", lambda *_a, **_k: [])
    monkeypatch.setattr(
        service,
        "_open_incident",
        lambda alert, triggered_value, db, send_notifications=True, sync_notifications=False: {
            "alert_id": str(alert.id),
            "triggered": True,
            "new_incident": True,
            "metric_value": triggered_value,
            "skipped_cooldown": False,
        },
    )

    result = service.evaluate_single_alert(alert=alert, db=_fake_db_for_alert(alert))
    assert result["triggered"] is True
    assert result["metric_value"] == 12.0


def test_evaluate_single_alert_missing_data_as_zero(monkeypatch):
    service = AlertEvaluationService()
    alert = _sample_alert()
    alert.metric_type = "number_of_calls"
    alert.operator = "<"
    alert.threshold_value = 1.0
    alert.alert_on_missing_data = True
    monkeypatch.setattr(service, "_compute_metric", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(service, "_get_open_incidents", lambda *_a, **_k: [])
    monkeypatch.setattr(
        service,
        "_open_incident",
        lambda alert, triggered_value, db, send_notifications=True, sync_notifications=False: {
            "alert_id": str(alert.id),
            "triggered": True,
            "new_incident": True,
            "metric_value": triggered_value,
        },
    )

    result = service.evaluate_single_alert(alert=alert, db=_fake_db_for_alert(alert))
    assert result["triggered"] is True
    assert result["metric_value"] == 0.0
