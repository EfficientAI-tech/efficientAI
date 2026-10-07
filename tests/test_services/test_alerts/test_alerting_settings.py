"""Alerting org sync settings."""

import uuid

import pytest
from fastapi import HTTPException

from app.models.database import Organization
from app.services.alerts.alerting_settings import (
    CONFIRM_PHRASE,
    get_org_alerting_settings,
    set_org_alerting_settings,
)


def test_default_sync_off(db_session, seed_org):
    org_id = uuid.uuid4()
    seed_org(org_id)
    settings = get_org_alerting_settings(org_id, db_session)
    assert settings["sync_notification_lifecycle"] is False


def test_enable_requires_confirmation(db_session, seed_org):
    org_id = uuid.uuid4()
    seed_org(org_id)
    with pytest.raises(HTTPException) as exc:
        set_org_alerting_settings(
            org_id,
            db_session,
            sync_notification_lifecycle=True,
            confirm_enable=True,
            confirmation_phrase="wrong",
        )
    assert exc.value.status_code == 400

    result = set_org_alerting_settings(
        org_id,
        db_session,
        sync_notification_lifecycle=True,
        confirm_enable=True,
        confirmation_phrase=CONFIRM_PHRASE,
    )
    assert result["sync_notification_lifecycle"] is True
