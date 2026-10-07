"""Alert history acknowledge/resolve lifecycle recording."""

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.models.database import Alert, AlertHistory, Organization
from app.models.enums import AlertHistoryStatus
from app.services.alerts.alerting_settings import CONFIRM_PHRASE, set_org_alerting_settings


@pytest.fixture
def alert_incident(db_session, seed_org):
    org_id = uuid.uuid4()
    seed_org(org_id)
    alert = Alert(
        id=uuid.uuid4(),
        organization_id=org_id,
        name="Test",
        metric_type="number_of_calls",
        aggregation="sum",
        operator=">",
        threshold_value=1,
        time_window_minutes=5,
        notify_frequency="immediate",
        status="active",
        notify_pagerduty_routing_keys=["key"],
    )
    history = AlertHistory(
        id=uuid.uuid4(),
        organization_id=org_id,
        alert_id=alert.id,
        triggered_at=datetime.now(timezone.utc),
        triggered_value=2,
        threshold_value=1,
        status=AlertHistoryStatus.NOTIFIED.value,
        notification_details={"results": [{"success": True, "channel": "pagerduty"}]},
    )
    db_session.add(alert)
    db_session.add(history)
    db_session.commit()
    return org_id, alert, history


def test_ack_records_lifecycle_when_sync_enabled(db_session, alert_incident):
    org_id, alert, history = alert_incident
    set_org_alerting_settings(
        org_id,
        db_session,
        sync_notification_lifecycle=True,
        confirm_enable=True,
        confirmation_phrase=CONFIRM_PHRASE,
    )

    fake_ack = [{"success": True, "channel": "pagerduty_acknowledge"}]

    with patch(
        "app.api.v1.routes.alerts.alert_notification_service.send_acknowledge_notifications",
        return_value=fake_ack,
    ):
        from app.api.v1.routes.alerts import update_alert_history
        from app.models.schemas import AlertHistoryUpdate

        class FakePrincipal:
            email = "admin@test.com"
            user_id = uuid.uuid4()

        updated = update_alert_history(
            history.id,
            AlertHistoryUpdate(status=AlertHistoryStatus.ACKNOWLEDGED),
            organization_id=org_id,
            principal=FakePrincipal(),
            db=db_session,
        )

    status = getattr(updated.status, "value", updated.status)
    assert status == AlertHistoryStatus.ACKNOWLEDGED.value
    assert updated.notification_details.get("lifecycle", {}).get("acknowledge") == fake_ack


def test_ack_skips_lifecycle_when_sync_disabled(db_session, alert_incident):
    org_id, _alert, history = alert_incident

    with patch(
        "app.api.v1.routes.alerts.alert_notification_service.send_acknowledge_notifications",
    ) as mock_send:
        from app.api.v1.routes.alerts import update_alert_history
        from app.models.schemas import AlertHistoryUpdate

        class FakePrincipal:
            email = "admin@test.com"
            user_id = uuid.uuid4()

        update_alert_history(
            history.id,
            AlertHistoryUpdate(status=AlertHistoryStatus.ACKNOWLEDGED),
            organization_id=org_id,
            principal=FakePrincipal(),
            db=db_session,
        )

    mock_send.assert_not_called()
