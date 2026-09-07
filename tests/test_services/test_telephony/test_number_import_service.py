"""Tests for provider-agnostic telephony number import."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.models.database import TelephonyIntegration, TelephonyPhoneNumber
from app.models.enums import TelephonyProvider
from app.services.telephony.number_import_service import (
    _extract_application_id,
    _normalize_country_iso2,
    _remote_metadata,
    import_numbers,
    list_available_numbers,
)


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
    assert (
        result["answer_url"]
        == "https://public.example.com/api/v1/telephony/plivo/webhooks/answer"
    )

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


def test_normalize_country_iso2_from_full_name():
    assert _normalize_country_iso2("India", e164="+918031725509") == "IN"


def test_normalize_country_iso2_from_two_letter_code():
    assert _normalize_country_iso2("US") == "US"


def test_normalize_country_iso2_from_e164_when_name_unknown():
    assert _normalize_country_iso2("Unknown Country", e164="+918031725509") == "IN"


def test_remote_metadata_normalizes_plivo_country_and_application_id():
    meta = _remote_metadata(
        TelephonyProvider.PLIVO.value,
        {
            "number": "+918031725509",
            "country": "India",
            "region": "Bangalore, INDIA",
            "Application": "/v1/Account/MA123/Application/30338906757027533/",
        },
        e164="+918031725509",
    )
    assert meta["country"] == "India"
    assert meta["country_iso2"] == "IN"
    assert meta["application_id"] == "30338906757027533"


@patch("app.services.telephony.number_import_service.telephony_service.get_provider_client")
@patch("app.services.telephony.number_import_service.telephony_service.get_org_integration")
def test_import_plivo_number_with_full_country_name(
    mock_get_integration, mock_get_client, db_session, org_id, seed_org, monkeypatch
):
    integration = _seed_plivo_integration(db_session, org_id)
    mock_get_integration.return_value = integration

    mock_client = MagicMock()
    mock_client.list_numbers.return_value = [
        {
            "number": "+918031725509",
            "country": "India",
            "region": "Bangalore, INDIA",
            "Application": "/v1/Account/MA123/Application/30338906757027533/",
        },
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
        numbers=["+918031725509"],
    )
    assert result["results"][0]["success"] is True

    row = (
        db_session.query(TelephonyPhoneNumber)
        .filter(
            TelephonyPhoneNumber.organization_id == org_id,
            TelephonyPhoneNumber.phone_number == "+918031725509",
        )
        .first()
    )
    assert row is not None
    assert row.country_iso2 == "IN"
    assert row.provider_app_id == "app-1"


def test_extract_application_id_from_plivo_uri():
    assert (
        _extract_application_id("/v1/Account/MA123/Application/30338906757027533/")
        == "30338906757027533"
    )
    assert _extract_application_id("30338906757027533") == "30338906757027533"


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
