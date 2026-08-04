"""Tests for provider-agnostic telephony number import."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.models.database import TelephonyIntegration, TelephonyPhoneNumber
from app.models.enums import TelephonyProvider
from app.services.telephony.number_import_service import import_numbers, list_available_numbers


def _seed_plivo_integration(db_session, org_id):
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
    db_session.commit()
    return integration


@patch("app.services.telephony.number_import_service.telephony_service.get_provider_client")
@patch("app.services.telephony.number_import_service.telephony_service.get_org_integration")
def test_list_available_plivo_numbers(mock_get_integration, mock_get_client, db_session, org_id, seed_org):
    integration = _seed_plivo_integration(db_session, org_id)
    mock_get_integration.return_value = integration

    mock_client = MagicMock()
    mock_client.list_numbers.return_value = [
        {"number": "+14155550100", "country": "US", "region": "California"},
    ]
    mock_get_client.return_value = mock_client

    results = list_available_numbers(db_session, org_id, TelephonyProvider.PLIVO.value)
    assert len(results) == 1
    assert results[0]["e164"] == "+14155550100"
    assert results[0]["already_imported"] is False


@patch("app.services.telephony.number_import_service.telephony_service.get_provider_client")
@patch("app.services.telephony.number_import_service.telephony_service.get_org_integration")
def test_import_plivo_number(mock_get_integration, mock_get_client, db_session, org_id, seed_org, monkeypatch):
    integration = _seed_plivo_integration(db_session, org_id)
    mock_get_integration.return_value = integration

    mock_client = MagicMock()
    mock_client.list_numbers.return_value = [
        {"number": "+14155550100", "country": "US", "region": "California"},
    ]
    mock_client.set_number_answer_url.return_value = (True, "Created Plivo application", "app-1")
    mock_get_client.return_value = mock_client

    monkeypatch.setattr(
        "app.services.telephony.number_import_service.settings.PLIVO_WEBHOOK_BASE_URL",
        "https://public.example.com",
    )
    monkeypatch.setattr(
        "app.services.telephony.number_import_service.settings.API_V1_PREFIX",
        "/api/v1",
    )

    result = import_numbers(
        db_session,
        org_id,
        TelephonyProvider.PLIVO.value,
        numbers=["+14155550100"],
    )
    assert result["provider"] == "plivo"
    assert result["results"][0]["success"] is True

    row = (
        db_session.query(TelephonyPhoneNumber)
        .filter(
            TelephonyPhoneNumber.organization_id == org_id,
            TelephonyPhoneNumber.phone_number == "+14155550100",
        )
        .first()
    )
    assert row is not None
    assert row.telephony_integration_id == integration.id


@patch("app.services.telephony.number_import_service.telephony_service.get_provider_client")
@patch("app.services.telephony.number_import_service.telephony_service.get_org_integration")
def test_list_available_exotel_numbers(mock_get_integration, mock_get_client, db_session, org_id, seed_org):
    integration = TelephonyIntegration(
        id=uuid4(),
        organization_id=org_id,
        provider=TelephonyProvider.EXOTEL.value,
        auth_id="exotel-key",
        auth_token="exotel-token",
        voice_app_id="acct-sid",
        sip_domain="api.exotel.com",
        is_active=True,
        is_default=True,
    )
    db_session.add(integration)
    db_session.commit()
    mock_get_integration.return_value = integration

    mock_client = MagicMock()
    mock_client.list_incoming_phone_numbers.return_value = [
        {"Sid": "exotel-num-1", "PhoneNumber": "08047114738", "FriendlyName": "Main"},
    ]
    mock_get_client.return_value = mock_client

    results = list_available_numbers(db_session, org_id, TelephonyProvider.EXOTEL.value)
    assert len(results) == 1
    assert results[0]["e164"] == "+918047114738"
    assert results[0]["provider_number_id"] == "exotel-num-1"
