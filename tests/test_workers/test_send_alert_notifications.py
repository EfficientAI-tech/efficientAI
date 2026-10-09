"""Queued alert notification delivery."""

from types import SimpleNamespace
from uuid import uuid4

from app.models.enums import AlertHistoryStatus
from app.services.alerts.alert_evaluation_service import OPEN_INCIDENT_STATUSES
from app.workers.tasks.send_alert_notifications import send_alert_notifications_task


def test_skips_resolved_incident_before_deliver(monkeypatch):
    alert = SimpleNamespace(id=uuid4())
    history = SimpleNamespace(
        id=uuid4(),
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
            if getattr(model, "__name__", "") == "AlertHistory":
                return FakeQuery(history)
            return FakeQuery(alert)

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(
        "app.workers.tasks.send_alert_notifications.SessionLocal",
        lambda: FakeDb(),
    )

    result = send_alert_notifications_task.run(str(alert.id), str(history.id), 1.0)

    assert result == {"skipped": f"incident status is {history.status}"}
    assert history.status not in OPEN_INCIDENT_STATUSES
