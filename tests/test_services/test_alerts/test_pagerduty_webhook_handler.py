"""PagerDuty inbound webhook handler."""

import uuid
from datetime import datetime, timezone

from app.models.database import Alert, AlertHistory, Organization
from app.models.enums import AlertHistoryStatus
from app.services.alerts.pagerduty_webhook_handler import (
    _history_id_from_dedup_key,
    apply_pagerduty_incident_event,
)


def test_history_id_from_dedup_key():
    hid = str(uuid.uuid4())
    assert _history_id_from_dedup_key(f"efficientai-incident-{hid}") == hid


def test_apply_acknowledge_updates_history(db_session, seed_org, org_id):
    org = db_session.query(Organization).filter_by(id=org_id).first()
    org.alerting_settings = {
        "sync_notification_lifecycle": True,
        "pagerduty_inbound_token": "tok",
    }
    db_session.commit()

    alert = Alert(
        id=uuid.uuid4(),
        organization_id=org_id,
        name="A",
        metric_type="number_of_calls",
        aggregation="sum",
        operator=">",
        threshold_value=1,
        time_window_minutes=5,
        notify_frequency="immediate",
        status="active",
    )
    history = AlertHistory(
        id=uuid.uuid4(),
        organization_id=org_id,
        alert_id=alert.id,
        triggered_at=datetime.now(timezone.utc),
        triggered_value=2,
        threshold_value=1,
        status=AlertHistoryStatus.NOTIFIED.value,
    )
    db_session.add(alert)
    db_session.add(history)
    db_session.commit()

    payload = {
        "event": {
            "event_type": "incident.acknowledged",
            "agent": {"summary": "oncall@example.com"},
            "data": {"incident_key": f"efficientai-incident-{history.id}"},
        }
    }
    ok, reason = apply_pagerduty_incident_event(org_id, payload, db_session)
    assert ok is True
    assert reason == "acknowledged"
    db_session.refresh(history)
    assert history.status == AlertHistoryStatus.ACKNOWLEDGED.value
    assert history.acknowledged_by == "oncall@example.com"
