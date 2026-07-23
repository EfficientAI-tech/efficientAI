"""API tests for Vobiz telephony webhooks and number import."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.models.database import CallRecording, CallRecordingSource, Organization, TelephonyIntegration, TelephonyPhoneNumber, Workspace
from app.models.enums import CallRecordingStatus, TelephonyProvider
from app.services.telephony.vobiz_session import create_call_session


def _patch_vobiz_webhook_base(monkeypatch, url: str = "https://public.example.com") -> str:
    wss = url.replace("https://", "wss://").replace("http://", "ws://")
    monkeypatch.setattr(
        "app.services.telephony.vobiz_agent_context.vobiz_webhook_base_url",
        lambda: url,
    )
    monkeypatch.setattr(
        "app.api.v1.routes.vobiz_telephony.vobiz_webhook_base_url",
        lambda: url,
    )
    monkeypatch.setattr(
        "app.services.media_urls.media_ws_base_url",
        lambda: wss,
    )
    return url


def _patch_vobiz_webhook_signature(monkeypatch):
    monkeypatch.setattr(
        "app.services.telephony.webhook_auth.validate_plivo_compatible_webhook_signature",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "app.services.telephony.webhook_auth.settings.VOBIZ_AUTH_TOKEN",
        "vobiz-auth-token",
    )


def _vobiz_webhook_headers() -> dict[str, str]:
    return {"X-Plivo-Signature": "test-signature"}


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

    _patch_vobiz_webhook_base(monkeypatch)
    _patch_vobiz_webhook_signature(monkeypatch)

    response = client.post(
        "/api/v1/telephony/vobiz/webhooks/answer",
        data={"To": "+919876543210", "From": "+919111111111", "CallUUID": "uuid-1"},
        headers=_vobiz_webhook_headers(),
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

    _patch_vobiz_webhook_base(monkeypatch)
    _patch_vobiz_webhook_signature(monkeypatch)

    response = client.post(
        f"/api/v1/telephony/vobiz/webhooks/answer?call_ref={session.call_ref}",
        data={"To": "+919111111111", "From": "+919876543210", "CallUUID": "uuid-2"},
        headers=_vobiz_webhook_headers(),
    )

    assert response.status_code == 200
    assert f"session={session.call_ref}" in response.text
    assert f"agent_id={agent.id}" in response.text


def test_vobiz_answer_webhook_includes_persona_scenario_from_session(
    client, org_id, seed_org, make_agent, make_persona, make_scenario, monkeypatch
):
    agent = make_agent()
    persona = make_persona()
    scenario = make_scenario()

    session = create_call_session(
        agent_id=str(agent.id),
        organization_id=str(org_id),
        direction="outbound",
        persona_id=str(persona.id),
        scenario_id=str(scenario.id),
    )

    _patch_vobiz_webhook_base(monkeypatch)
    _patch_vobiz_webhook_signature(monkeypatch)

    response = client.post(
        f"/api/v1/telephony/vobiz/webhooks/answer?call_ref={session.call_ref}",
        data={"To": "+919111111111", "From": "+919876543210", "CallUUID": "uuid-3"},
        headers=_vobiz_webhook_headers(),
    )

    assert response.status_code == 200
    assert f"persona_id={persona.id}" in response.text
    assert f"scenario_id={scenario.id}" in response.text


def test_vobiz_answer_webhook_rejects_unconfigured_number(client, db_session, org_id, seed_org, monkeypatch):
    _patch_vobiz_webhook_signature(monkeypatch)
    response = client.post(
        "/api/v1/telephony/vobiz/webhooks/answer",
        data={"To": "+919000000000", "From": "+919111111111"},
        headers=_vobiz_webhook_headers(),
    )
    assert response.status_code == 403


def test_vobiz_answer_webhook_rejects_missing_signature(client, db_session, org_id, seed_org, make_agent):
    agent = make_agent()
    _seed_vobiz_phone(db_session, org_id, agent_id=agent.id)

    response = client.post(
        "/api/v1/telephony/vobiz/webhooks/answer",
        data={"To": "+919876543210", "From": "+919111111111"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Missing webhook signature"


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


def test_vobiz_events_webhook_updates_call_by_call_ref(client, db_session, org_id, seed_org, make_agent, monkeypatch):
    agent = make_agent()
    _seed_vobiz_phone(db_session, org_id)
    _patch_vobiz_webhook_signature(monkeypatch)
    call_ref = "outbound-ref-1"
    row = CallRecording(
        organization_id=org_id,
        workspace_id=agent.workspace_id,
        call_short_id="111222",
        status=CallRecordingStatus.PENDING,
        source=CallRecordingSource.WEBHOOK,
        call_event="call_in_progress",
        call_data={"call_ref": call_ref, "live_transcript": []},
        provider_call_id="call-uuid-events",
        provider_platform="vobiz",
        agent_id=agent.id,
    )
    db_session.add(row)
    db_session.commit()

    response = client.post(
        f"/api/v1/telephony/vobiz/webhooks/events?call_ref={call_ref}",
        data={"CallUUID": "call-uuid-events", "CallStatus": "completed"},
        headers=_vobiz_webhook_headers(),
    )
    assert response.status_code == 200

    db_session.expire_all()
    updated = db_session.query(CallRecording).filter(CallRecording.id == row.id).first()
    assert updated.call_event == "call_ended"
    assert updated.call_data.get("ended_at")


@patch("app.api.v1.routes.vobiz_telephony.ingest_carrier_recording_url")
def test_vobiz_recording_ready_webhook_finds_call_by_request_uuid(
    mock_ingest,
    client, db_session, org_id, seed_org, make_agent, monkeypatch
):
    agent = make_agent()
    _seed_vobiz_phone(db_session, org_id)
    _patch_vobiz_webhook_signature(monkeypatch)
    call_ref = "outbound-ref-2"
    row = CallRecording(
        organization_id=org_id,
        workspace_id=agent.workspace_id,
        call_short_id="333444",
        status=CallRecordingStatus.PENDING,
        source=CallRecordingSource.WEBHOOK,
        call_event="call_ended",
        call_data={
            "call_ref": call_ref,
            "request_uuid": "request-uuid-rec",
            "live_transcript": [],
        },
        provider_call_id="request-uuid-rec",
        provider_platform="vobiz",
        agent_id=agent.id,
    )
    db_session.add(row)
    db_session.commit()

    response = client.post(
        "/api/v1/telephony/vobiz/webhooks/recording-ready",
        data={
            "CallUUID": "request-uuid-rec",
            "RecordUrl": "https://recordings.example.com/call.wav",
        },
        headers=_vobiz_webhook_headers(),
    )
    assert response.status_code == 200

    db_session.expire_all()
    updated = db_session.query(CallRecording).filter(CallRecording.id == row.id).first()
    assert updated.call_data.get("recording_url") == "https://recordings.example.com/call.wav"
    mock_ingest.assert_called_once()


@patch("app.api.v1.routes.vobiz_telephony.initiate_vobiz_outbound_call_task")
@patch("app.api.v1.routes.vobiz_telephony.build_vobiz_client_for_org")
@patch("app.api.v1.routes.vobiz_telephony.resolve_outbound_from_number")
@patch("app.api.v1.routes.vobiz_telephony.vobiz_webhook_base_url")
def test_create_vobiz_outbound_call_stamps_workspace_id(
    mock_base_url,
    mock_resolve_from,
    mock_build_client,
    mock_outbound_task,
    client,
    db_session,
    org_id,
    seed_org,
    make_agent,
):
    agent = make_agent()
    mock_base_url.return_value = "https://public.example.com"
    mock_resolve_from.return_value = ("+919876543210", False)
    mock_build_client.return_value = (MagicMock(), None)
    mock_outbound_task.delay.return_value = None

    response = client.post(
        "/api/v1/telephony/vobiz/calls/outbound",
        json={
            "to_number": "+919111111111",
            "agent_id": str(agent.id),
            "from_number": "+919876543210",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["call_status"] == "queued"
    assert body["call_ref"]
    assert body["call_short_id"]
    mock_outbound_task.delay.assert_called_once()
    task_kwargs = mock_outbound_task.delay.call_args.kwargs
    assert f"call_ref={body['call_ref']}" in task_kwargs["events_url"]

    recording = (
        db_session.query(CallRecording)
        .filter(CallRecording.call_short_id == body["call_short_id"])
        .first()
    )
    assert recording is not None
    assert recording.workspace_id == agent.workspace_id
    assert recording.agent_id == agent.id
    assert recording.organization_id == org_id


@patch("app.api.v1.routes.vobiz_telephony.initiate_vobiz_outbound_call_task")
@patch("app.api.v1.routes.vobiz_telephony.build_vobiz_client_for_org")
@patch("app.api.v1.routes.vobiz_telephony.resolve_outbound_from_number")
@patch("app.api.v1.routes.vobiz_telephony.vobiz_webhook_base_url")
def test_create_vobiz_outbound_call_stores_persona_scenario_in_session(
    mock_base_url,
    mock_resolve_from,
    mock_build_client,
    mock_outbound_task,
    client,
    org_id,
    seed_org,
    make_agent,
    make_persona,
    make_scenario,
):
    from app.services.telephony.vobiz_session import get_call_session

    agent = make_agent()
    persona = make_persona()
    scenario = make_scenario()
    mock_base_url.return_value = "https://public.example.com"
    mock_resolve_from.return_value = ("+919876543210", False)
    mock_build_client.return_value = (MagicMock(), None)
    mock_outbound_task.delay.return_value = None

    response = client.post(
        "/api/v1/telephony/vobiz/calls/outbound",
        json={
            "to_number": "+919111111111",
            "agent_id": str(agent.id),
            "persona_id": str(persona.id),
            "scenario_id": str(scenario.id),
        },
    )

    assert response.status_code == 200
    call_ref = response.json()["call_ref"]
    session = get_call_session(call_ref)
    assert session is not None
    assert session.persona_id == str(persona.id)
    assert session.scenario_id == str(scenario.id)


@patch("app.api.v1.routes.vobiz_telephony.initiate_vobiz_outbound_call_task")
@patch("app.api.v1.routes.vobiz_telephony.build_vobiz_client_for_org")
@patch("app.api.v1.routes.vobiz_telephony.resolve_outbound_from_number")
@patch("app.api.v1.routes.vobiz_telephony.vobiz_webhook_base_url")
def test_create_vobiz_outbound_call_resolves_evaluator_context(
    mock_base_url,
    mock_resolve_from,
    mock_build_client,
    mock_outbound_task,
    client,
    make_agent,
    make_persona,
    make_scenario,
    make_evaluator,
):
    from app.services.telephony.vobiz_session import get_call_session

    agent = make_agent()
    persona = make_persona()
    scenario = make_scenario()
    evaluator = make_evaluator(agent_id=agent.id, persona_id=persona.id, scenario_id=scenario.id)

    mock_base_url.return_value = "https://public.example.com"
    mock_resolve_from.return_value = ("+919876543210", False)
    mock_build_client.return_value = (MagicMock(), None)
    mock_outbound_task.delay.return_value = None

    response = client.post(
        "/api/v1/telephony/vobiz/calls/outbound",
        json={
            "to_number": "+919111111111",
            "agent_id": str(agent.id),
            "evaluator_id": str(evaluator.id),
        },
    )

    assert response.status_code == 200
    session = get_call_session(response.json()["call_ref"])
    assert session.persona_id == str(persona.id)
    assert session.scenario_id == str(scenario.id)
    assert session.evaluator_id == str(evaluator.id)
