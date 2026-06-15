"""API tests for Plivo telephony webhooks."""

from uuid import uuid4

import pytest

from app.models.database import (
    CallRecording,
    CallRecordingSource,
    CallRecordingStatus,
    TelephonyIntegration,
    TelephonyPhoneNumber,
    Workspace,
)
from app.models.enums import TelephonyProvider


def _seed_plivo_phone(db_session, org_id, *, phone_number="+15551234567"):
    integration = TelephonyIntegration(
        id=uuid4(),
        organization_id=org_id,
        provider=TelephonyProvider.PLIVO.value,
        auth_id="plivo-auth-id",
        auth_token="plivo-auth-token",
        is_active=True,
        is_default=True,
    )
    db_session.add(integration)
    db_session.flush()

    number = TelephonyPhoneNumber(
        id=uuid4(),
        organization_id=org_id,
        telephony_integration_id=integration.id,
        phone_number=phone_number,
        is_active=True,
    )
    db_session.add(number)
    db_session.commit()
    return integration, number


def _seed_call_recording(db_session, org_id, *, call_uuid="call-uuid-123"):
    workspace = (
        db_session.query(Workspace)
        .filter(Workspace.organization_id == org_id, Workspace.is_default.is_(True))
        .first()
    )
    integration = TelephonyIntegration(
        id=uuid4(),
        organization_id=org_id,
        provider=TelephonyProvider.PLIVO.value,
        auth_id="plivo-auth-id",
        auth_token="plivo-auth-token",
        is_active=True,
        is_default=True,
    )
    db_session.add(integration)
    db_session.flush()

    recording = CallRecording(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=workspace.id,
        call_short_id="123456",
        status=CallRecordingStatus.PENDING,
        source=CallRecordingSource.PLAYGROUND,
        provider_call_id=call_uuid,
    )
    db_session.add(recording)
    db_session.commit()
    return recording


def test_answer_webhook_rejects_missing_signature(client, db_session, org_id, seed_org):
    _seed_plivo_phone(db_session, org_id)

    response = client.post(
        "/api/v1/telephony/webhooks/answer",
        data={"To": "+15551234567", "From": "+15559876543", "CallUUID": "uuid-1"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Missing webhook signature"


def test_answer_webhook_rejects_invalid_signature(
    client, db_session, org_id, seed_org, monkeypatch
):
    _seed_plivo_phone(db_session, org_id)
    monkeypatch.setattr(
        "plivo.utils.validate_signature",
        lambda *_args, **_kwargs: False,
    )

    response = client.post(
        "/api/v1/telephony/webhooks/answer",
        data={"To": "+15551234567", "From": "+15559876543", "CallUUID": "uuid-1"},
        headers={"X-Plivo-Signature": "bad-signature"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Invalid webhook signature"


def test_answer_webhook_accepts_valid_signature(
    client, db_session, org_id, seed_org, monkeypatch
):
    _seed_plivo_phone(db_session, org_id)
    monkeypatch.setattr(
        "plivo.utils.validate_signature",
        lambda *_args, **_kwargs: True,
    )

    response = client.post(
        "/api/v1/telephony/webhooks/answer",
        data={"To": "+15551234567", "From": "+15559876543", "CallUUID": "uuid-1"},
        headers={"X-Plivo-Signature": "valid-signature"},
    )

    assert response.status_code == 200
    assert "application/xml" in response.headers["content-type"]


def test_events_webhook_rejects_unknown_call_uuid(client, db_session, org_id, seed_org):
    response = client.post(
        "/api/v1/telephony/webhooks/events",
        data={"CallUUID": "unknown-call", "CallStatus": "completed"},
        headers={"X-Plivo-Signature": "any-signature"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Invalid webhook signature"


def test_events_webhook_accepts_valid_signature(
    client, db_session, org_id, seed_org, monkeypatch
):
    recording = _seed_call_recording(db_session, org_id, call_uuid="known-call")
    monkeypatch.setattr(
        "plivo.utils.validate_signature",
        lambda *_args, **_kwargs: True,
    )

    response = client.post(
        "/api/v1/telephony/webhooks/events",
        data={"CallUUID": recording.provider_call_id, "CallStatus": "completed"},
        headers={"X-Plivo-Signature": "valid-signature"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
