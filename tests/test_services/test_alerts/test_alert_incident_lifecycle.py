"""Incident-style alerting: one open breach per alert, auto-recover on OK."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.models.enums import AlertHistoryStatus
from app.services.alerts.alert_evaluation_service import AlertEvaluationService


def _sample_alert():
    return SimpleNamespace(
        id=uuid4(),
        name="Evals Alert",
        operator=">",
        threshold_value=1.0,
        notify_frequency="immediate",
        metric_type="number_of_calls",
        aggregation="sum",
        time_window_minutes=60,
        organization_id=uuid4(),
        agent_ids=None,
        notify_webhooks=[],
        notify_pagerduty_routing_keys=[],
    )


def _incident_row(**overrides):
    base = {
        "id": uuid4(),
        "status": AlertHistoryStatus.ACKNOWLEDGED.value,
        "triggered_at": datetime.now(timezone.utc) - timedelta(hours=1),
        "triggered_value": 3.0,
        "notified_at": datetime.now(timezone.utc) - timedelta(hours=1),
        "context_data": {},
        "notification_details": None,
        "resolution_notes": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_ongoing_incident_does_not_open_new_history(monkeypatch):
    service = AlertEvaluationService()
    alert = _sample_alert()
    incident = _incident_row()

    class FakeQuery:
        def filter(self, *_a, **_k):
            return self

        def order_by(self, *_a, **_k):
            return self

        def with_for_update(self):
            return self

        def first(self):
            return alert

        def all(self):
            return [incident]

    class FakeDb:
        def query(self, _model):
            return FakeQuery()

        def commit(self):
            pass

    monkeypatch.setattr(service, "_compute_metric", lambda *_a, **_k: 3.0)
    monkeypatch.setattr(service, "_deliver_notifications", lambda *_a, **_k: [])

    result = service.evaluate_single_alert(alert=alert, db=FakeDb())

    assert result["triggered"] is True
    assert result["ongoing_incident"] is True
    assert result["new_incident"] is False
    assert result["skipped_cooldown"] is True
    assert incident.triggered_value == 3.0


def test_condition_ok_requires_two_evaluations_before_auto_resolve(monkeypatch):
    service = AlertEvaluationService()
    alert = _sample_alert()
    incident = _incident_row()

    class FakeQuery:
        def filter(self, *_a, **_k):
            return self

        def order_by(self, *_a, **_k):
            return self

        def with_for_update(self):
            return self

        def first(self):
            return alert

        def all(self):
            return [incident]

    class FakeDb:
        def query(self, _model):
            return FakeQuery()

        def commit(self):
            pass

    monkeypatch.setattr(service, "_compute_metric", lambda *_a, **_k: 1.0)
    monkeypatch.setattr(
        "app.services.alerts.alerting_settings.is_lifecycle_sync_enabled",
        lambda *_a, **_k: False,
    )

    first = service.evaluate_single_alert(alert=alert, db=FakeDb())
    assert first["triggered"] is False
    assert first.get("recovering") is True
    assert incident.status == AlertHistoryStatus.ACKNOWLEDGED.value

    second = service.evaluate_single_alert(alert=alert, db=FakeDb())
    assert second["recovered"] is True
    assert incident.status == AlertHistoryStatus.RESOLVED.value
    assert incident.resolved_by == "system"


def test_should_notify_immediate_only_on_first_send():
    service = AlertEvaluationService()
    alert = _sample_alert()
    incident = _incident_row(notified_at=datetime.now(timezone.utc))
    incident.status = AlertHistoryStatus.NOTIFIED.value

    assert service._should_notify_for_incident(alert, incident) is False

    incident.notified_at = None
    incident.status = AlertHistoryStatus.NOTIFIED.value
    assert service._should_notify_for_incident(alert, incident) is False

    incident.status = AlertHistoryStatus.TRIGGERED.value
    assert service._should_notify_for_incident(alert, incident) is True
