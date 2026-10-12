"""Suppress re-open after manual resolve."""

from types import SimpleNamespace
from uuid import uuid4

from app.services.alerts.alert_evaluation_service import AlertEvaluationService


def _fake_db(alert):
    class FakeQuery:
        def filter(self, *_a, **_k):
            return self

        def with_for_update(self):
            return self

        def first(self):
            return alert

        def order_by(self, *_a, **_k):
            return self

        def all(self):
            return []

    class FakeDb:
        def query(self, _model):
            return FakeQuery()

        def commit(self):
            pass

    return FakeDb()


def test_breach_suppressed_when_flag_set(monkeypatch):
    service = AlertEvaluationService()
    alert = SimpleNamespace(
        id=uuid4(),
        name="A",
        operator=">",
        threshold_value=1.0,
        suppress_reopen_until_ok=True,
        organization_id=uuid4(),
    )
    monkeypatch.setattr(service, "_compute_metric", lambda *_a, **_k: 5.0)

    result = service.evaluate_single_alert(alert, _fake_db(alert))

    assert result.get("suppressed") is True
    assert result["triggered"] is False
