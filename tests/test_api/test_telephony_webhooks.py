"""API tests for Plivo telephony webhooks."""

from uuid import uuid4

import pytest

from app.models.database import (
    Agent,
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
        inbound_enabled=True,
        outbound_enabled=True,
        source="imported",
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
        "app.services.telephony.webhook_auth.validate_plivo_compatible_webhook_signature",
        lambda *_args, **_kwargs: False,
    )

    response = client.post(
        "/api/v1/telephony/webhooks/answer",
        data={"To": "+15551234567", "From": "+15559876543", "CallUUID": "uuid-1"},
        headers={"X-Plivo-Signature": "bad-signature"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Invalid webhook signature"


@pytest.mark.parametrize(
    "webhook_path",
    [
        "/api/v1/telephony/webhooks/answer",
        "/api/v1/telephony/plivo/webhooks/answer",
    ],
)
def test_answer_webhook_accepts_valid_signature(
    client, db_session, org_id, seed_org, monkeypatch, webhook_path
):
    _seed_plivo_phone(db_session, org_id)
    monkeypatch.setattr(
        "app.services.telephony.webhook_auth.validate_plivo_compatible_webhook_signature",
        lambda *_args, **_kwargs: True,
    )

    response = client.post(
        webhook_path,
        data={"To": "+15551234567", "From": "+15559876543", "CallUUID": "uuid-1"},
        headers={"X-Plivo-Signature": "valid-signature"},
    )

    assert response.status_code == 200
    assert "application/xml" in response.headers["content-type"]


@pytest.mark.parametrize(
    "webhook_path",
    [
        "/api/v1/telephony/webhooks/events",
        "/api/v1/telephony/plivo/webhooks/events",
    ],
)
def test_events_webhook_accepts_valid_signature(
    client, db_session, org_id, seed_org, monkeypatch, webhook_path
):
    recording = _seed_call_recording(db_session, org_id, call_uuid="known-call")
    monkeypatch.setattr(
        "app.services.telephony.webhook_auth.validate_plivo_compatible_webhook_signature",
        lambda *_args, **_kwargs: True,
    )

    response = client.post(
        webhook_path,
        data={"CallUUID": recording.provider_call_id, "CallStatus": "completed"},
        headers={"X-Plivo-Signature": "valid-signature"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_answer_webhook_streams_to_voice_agent_when_number_linked(
    client, db_session, org_id, seed_org, default_workspace, monkeypatch
):
    """Inbound Plivo answer should return Stream XML, not PSTN dial, for linked agents."""
    phone_number = "+918031725509"
    integration, number = _seed_plivo_phone(db_session, org_id, phone_number=phone_number)
    del integration

    agent = Agent(
        id=uuid4(),
        agent_id="100001",
        organization_id=org_id,
        workspace_id=default_workspace.id,
        name="Inbound Agent",
        phone_number=phone_number,
        language="en",
        description="Inbound test agent",
        call_type="inbound",
        call_medium="phone_call",
        telephony_phone_number_id=number.id,
    )
    db_session.add(agent)
    db_session.flush()
    number.agent_id = agent.id
    number.inbound_enabled = True
    db_session.commit()

    monkeypatch.setattr(
        "app.services.telephony.webhook_auth.validate_plivo_compatible_webhook_signature",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "app.services.telephony.inbound_stream_answer.build_carrier_ws_url",
        lambda **_kwargs: "wss://example.test/api/v1/telephony/carrier/ws?agent_id=a&session=s",
    )

    response = client.post(
        "/api/v1/telephony/plivo/webhooks/answer",
        data={"To": "918031725509", "From": "917259483185", "CallUUID": "uuid-inbound"},
        headers={"X-Plivo-Signature": "valid-signature"},
    )

    assert response.status_code == 200
    assert "application/xml" in response.headers["content-type"]
    body = response.text
    assert "<Stream" in body
    assert "wss://example.test/api/v1/telephony/carrier/ws" in body
    assert "<Dial" not in body


def test_events_webhook_accepts_valid_signature_without_call_recording(
    client, db_session, org_id, seed_org, monkeypatch
):
    """Inbound hangup events should verify using the imported DID when no CallRecording exists."""
    phone_number = "+918031725509"
    _seed_plivo_phone(db_session, org_id, phone_number=phone_number)
    monkeypatch.setattr(
        "app.services.telephony.webhook_auth.validate_plivo_compatible_webhook_signature",
        lambda *_args, **_kwargs: True,
    )

    response = client.post(
        "/api/v1/telephony/plivo/webhooks/events",
        data={
            "CallUUID": "inbound-call-without-recording",
            "CallStatus": "completed",
            "To": phone_number,
            "From": "+919876543210",
        },
        headers={"X-Plivo-Signature": "valid-signature"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_events_webhook_rejects_unknown_call_uuid(client, db_session, org_id, seed_org):
    response = client.post(
        "/api/v1/telephony/webhooks/events",
        data={"CallUUID": "unknown-call", "CallStatus": "completed"},
        headers={"X-Plivo-Signature": "any-signature"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Invalid webhook signature"


def test_delete_telephony_config_unlinks_phone_numbers(client, db_session, org_id, seed_org):
    integration, number = _seed_plivo_phone(db_session, org_id)

    response = client.delete(f"/api/v1/telephony/config/{integration.id}")

    assert response.status_code == 204

    db_session.expire_all()
    deleted_integration = (
        db_session.query(TelephonyIntegration)
        .filter(TelephonyIntegration.id == integration.id)
        .first()
    )
    assert deleted_integration is None

    refreshed_number = (
        db_session.query(TelephonyPhoneNumber)
        .filter(TelephonyPhoneNumber.id == number.id)
        .first()
    )
    assert refreshed_number is not None
    assert refreshed_number.is_active is True
    assert refreshed_number.telephony_integration_id is None
