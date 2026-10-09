"""Queued alert notification delivery."""

from types import SimpleNamespace
from uuid import uuid4

from app.models.enums import AlertHistoryStatus
from app.services.alerts.alert_evaluation_service import OPEN_INCIDENT_STATUSES
from app.workers.tasks.send_alert_notifications import send_alert_notifications_task


def test_skips_resolved_incident_before_deliver(monkeypatch):
    alert_id = uuid4()
    history_id = uuid4()
    alert = SimpleNamespace(id=alert_id)
    history = SimpleNamespace(
        id=history_id,
        status=AlertHistoryStatus.RESOLVED.value,
    )

    class FakeQuery:
        def __init__(self, row):
            self._row = row

        def filter(self, *_a, **_k):
            return self

        def with_for_update(self):
            return self

        def first(self):
            return self._row

    class FakeDb:
        def query(self, model):
            name = getattr(model, "__name__", "")
            if name == "AlertHistory":
                return FakeQuery(history)
            return FakeQuery(alert)

        def rollback(self):
            pass

        def close(self):
            pass

    deliver_called = False

    def fake_deliver(*_a, **_k):
        nonlocal deliver_called
        deliver_called = True
        return []

    monkeypatch.setattr(
        "app.workers.tasks.send_alert_notifications.SessionLocal",
        lambda: FakeDb(),
    )
    class FakeEvalService:
        def _should_notify_for_incident(self, *_a, **_k):
            return True

        def deliver_notifications_for_history(self, *_a, **_k):
            return fake_deliver()

    monkeypatch.setattr(
        "app.services.alerts.alert_evaluation_service.alert_evaluation_service",
        FakeEvalService(),
    )

    result = send_alert_notifications_task.run(
        str(alert_id), str(history_id), 1.0
    )

    assert result["skipped"] == f"incident status is {AlertHistoryStatus.RESOLVED.value}"
    assert deliver_called is False
    assert AlertHistoryStatus.RESOLVED.value not in OPEN_INCIDENT_STATUSES
