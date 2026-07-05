"""API tests for Vobiz telephony webhooks and number import."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.models.database import Organization, TelephonyIntegration, TelephonyPhoneNumber, Workspace
from app.models.enums import TelephonyProvider
from app.services.telephony.vobiz_session import create_call_session


def _seed_vobiz_phone(db_session, org_id, *, phone_number="+919876543210", agent_id=None):
    workspace = (
        db_session.query(Workspace)
        .filter(Workspace.organization_id == org_id, Workspace.is_default.is_(True))
        .first()
    )
    integration = TelephonyIntegration(
        id=uuid4(),
        organization_id=org_id,
        provider=TelephonyProvider.VOBIZ.value,
        auth_id="vobiz-auth-id",
        auth_token="vobiz-auth-token",
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
        agent_id=agent_id,
    )
    db_session.add(number)
    db_session.commit()
    return integration, number


def test_vobiz_answer_webhook_returns_stream_xml(client, db_session, org_id, seed_org, make_agent, monkeypatch):
    agent = make_agent()
    _seed_vobiz_phone(db_session, org_id, agent_id=agent.id)

    monkeypatch.setattr(
        "app.api.v1.routes.vobiz_telephony.vobiz_webhook_base_url",
        lambda: "https://public.example.com",
    )

    response = client.post(
        "/api/v1/telephony/vobiz/webhooks/answer",
        data={"To": "+919876543210", "From": "+919111111111", "CallUUID": "uuid-1"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    body = response.text
    assert "<Stream bidirectional=\"true\"" in body
    assert "wss://public.example.com/api/v1/telephony/vobiz/ws" in body
    assert f"agent_id={agent.id}" in body


def test_vobiz_answer_webhook_uses_outbound_call_ref(client, db_session, org_id, seed_org, make_agent, monkeypatch):
    agent = make_agent()

    session = create_call_session(
        agent_id=str(agent.id),
        organization_id=str(org_id),
        direction="outbound",
    )

    monkeypatch.setattr(
        "app.api.v1.routes.vobiz_telephony.vobiz_webhook_base_url",
        lambda: "https://public.example.com",
    )

    response = client.post(
        f"/api/v1/telephony/vobiz/webhooks/answer?call_ref={session.call_ref}",
        data={"To": "+919111111111", "From": "+919876543210", "CallUUID": "uuid-2"},
    )

    assert response.status_code == 200
    assert f"session={session.call_ref}" in response.text
    assert f"agent_id={agent.id}" in response.text


def test_vobiz_answer_webhook_rejects_unconfigured_number(client, db_session, org_id, seed_org):
    response = client.post(
        "/api/v1/telephony/vobiz/webhooks/answer",
        data={"To": "+919000000000", "From": "+919111111111"},
    )
    assert response.status_code == 200
    assert "No active routing" in response.text


def test_vobiz_inbound_routing_is_org_scoped(db_session, org_id, seed_org, make_agent):
    from app.services.telephony.phone_routing import resolve_inbound_agent_for_number

    other_org_id = uuid4()
    other_org = Organization(id=other_org_id, name="Other Org")
    db_session.add(other_org)
    db_session.commit()

    agent = make_agent()
    _seed_vobiz_phone(db_session, org_id, phone_number="+919876543210", agent_id=agent.id)

    resolved_agent_id, resolved_org_id = resolve_inbound_agent_for_number(db_session, "+919876543210")
    assert resolved_agent_id == agent.id
    assert resolved_org_id == org_id


@patch("app.api.v1.routes.vobiz_telephony.list_available_vobiz_numbers")
def test_list_vobiz_available_numbers(mock_list, client, org_id, seed_org):
    mock_list.return_value = [
        {
            "e164": "+919876543210",
            "already_imported": False,
            "country": "IN",
        }
    ]

    response = client.get("/api/v1/telephony/vobiz/numbers/available")
    assert response.status_code == 200
    data = response.json()
    assert data[0]["e164"] == "+919876543210"
    assert data[0]["already_imported"] is False


@patch("app.api.v1.routes.vobiz_telephony.configured_outbound_pool")
def test_get_vobiz_outbound_pool(mock_pool, client, org_id, seed_org, monkeypatch):
    mock_pool.return_value = ["+918071579610", "+919876543210"]
    monkeypatch.setattr(
        "app.api.v1.routes.vobiz_telephony.settings.VOBIZ_OUTBOUND_POOL_MAX_CONCURRENT_PER_ORG",
        5,
    )

    response = client.get("/api/v1/telephony/vobiz/outbound-pool")
    assert response.status_code == 200
    body = response.json()
    assert body["numbers"] == ["+918071579610", "+919876543210"]
    assert body["max_concurrent_per_org"] == 5
    assert body["shared_across_orgs"] is True


@patch("app.api.v1.routes.vobiz_telephony.import_vobiz_numbers")
def test_import_vobiz_numbers_route(mock_import, client, org_id, seed_org):
    mock_import.return_value = {
        "answer_url": "https://public.example.com/api/v1/telephony/vobiz/webhooks/answer",
        "results": [
            {
                "number": "+919876543210",
                "success": True,
                "message": "Created and attached Vobiz application",
                "answer_url": "https://public.example.com/api/v1/telephony/vobiz/webhooks/answer",
                "webhook_configured": True,
                "imported_number_id": str(uuid4()),
            }
        ],
    }

    response = client.post(
        "/api/v1/telephony/vobiz/numbers/import",
        json={"numbers": ["+919876543210"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["results"][0]["success"] is True
    assert "answer_url" in body


def test_delete_imported_vobiz_number_removes_row(client, db_session, org_id, seed_org):
    integration, number = _seed_vobiz_phone(db_session, org_id)

    response = client.delete(f"/api/v1/telephony/vobiz/numbers/{number.id}")
    assert response.status_code == 204

    db_session.expire_all()
    assert (
        db_session.query(TelephonyPhoneNumber)
        .filter(TelephonyPhoneNumber.id == number.id)
        .first()
        is None
    )

    list_response = client.get("/api/v1/telephony/numbers")
    assert list_response.status_code == 200
    assert list_response.json() == []


def test_delete_inactive_imported_vobiz_number(client, db_session, org_id, seed_org):
    _, number = _seed_vobiz_phone(db_session, org_id)
    number.is_active = False
    number.inbound_enabled = False
    db_session.commit()

    response = client.delete(f"/api/v1/telephony/vobiz/numbers/{number.id}")
    assert response.status_code == 204

    db_session.expire_all()
    assert (
        db_session.query(TelephonyPhoneNumber)
        .filter(TelephonyPhoneNumber.id == number.id)
        .first()
        is None
    )
