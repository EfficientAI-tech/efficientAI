"""Tests for multi-provider platform outbound pool configuration."""

import pytest

from app.services.telephony.platform_outbound_pool import (
    PlatformOutboundPoolEntry,
    configured_outbound_pool,
    configured_outbound_pool_numbers,
    outbound_pool_api_payload,
    pool_max_concurrent_per_org,
    resolve_outbound_from_number,
)


@pytest.fixture
def clear_pool_settings(monkeypatch):
    monkeypatch.setattr("app.services.telephony.platform_outbound_pool.settings.TELEPHONY_OUTBOUND_POOL", [])
    monkeypatch.setattr("app.services.telephony.platform_outbound_pool.settings.VOBIZ_OUTBOUND_POOL", [])
    monkeypatch.setattr("app.services.telephony.platform_outbound_pool.settings.VOBIZ_FROM_NUMBER", "")
    monkeypatch.setattr("app.services.telephony.platform_outbound_pool.settings.PLIVO_OUTBOUND_POOL", [])
    monkeypatch.setattr("app.services.telephony.platform_outbound_pool.settings.EXOTEL_OUTBOUND_POOL", [])
    monkeypatch.setattr(
        "app.services.telephony.platform_outbound_pool.settings.TELEPHONY_OUTBOUND_POOL_MAX_CONCURRENT_PER_ORG",
        None,
    )
    monkeypatch.setattr(
        "app.services.telephony.platform_outbound_pool.settings.VOBIZ_OUTBOUND_POOL_MAX_CONCURRENT_PER_ORG",
        5,
    )


def test_configured_outbound_pool_merges_telephony_and_legacy_vobiz(clear_pool_settings, monkeypatch):
    monkeypatch.setattr(
        "app.services.telephony.platform_outbound_pool.settings.TELEPHONY_OUTBOUND_POOL",
        [{"number": "+918011223344", "provider": "plivo"}],
    )
    monkeypatch.setattr(
        "app.services.telephony.platform_outbound_pool.settings.VOBIZ_OUTBOUND_POOL",
        ["+918011223345"],
    )
    monkeypatch.setattr(
        "app.services.telephony.platform_outbound_pool.settings.VOBIZ_FROM_NUMBER",
        "+918011223344",
    )

    entries = configured_outbound_pool()
    assert entries == [
        PlatformOutboundPoolEntry(phone_number="+918011223344", provider="plivo"),
        PlatformOutboundPoolEntry(phone_number="+918011223345", provider="vobiz"),
    ]
    assert configured_outbound_pool_numbers() == ["+918011223344", "+918011223345"]


def test_outbound_pool_api_payload_includes_provider_metadata(clear_pool_settings, monkeypatch):
    monkeypatch.setattr(
        "app.services.telephony.platform_outbound_pool.settings.TELEPHONY_OUTBOUND_POOL",
        [
            {"number": "+918011223344", "provider": "exotel"},
            {"phone_number": "+918011223345", "provider": "twilio"},
        ],
    )
    monkeypatch.setattr(
        "app.services.telephony.platform_outbound_pool.settings.TELEPHONY_OUTBOUND_POOL_MAX_CONCURRENT_PER_ORG",
        8,
    )

    payload = outbound_pool_api_payload()
    assert payload["numbers"] == [
        {"phone_number": "+918011223344", "provider": "exotel"},
        {"phone_number": "+918011223345", "provider": "twilio"},
    ]
    assert payload["max_concurrent_per_org"] == 8
    assert payload["shared_across_orgs"] is True
    assert pool_max_concurrent_per_org() == 8


def test_resolve_outbound_from_number_returns_pool_provider(
    clear_pool_settings, monkeypatch, db_session, org_id, seed_org
):
    monkeypatch.setattr(
        "app.services.telephony.platform_outbound_pool.settings.TELEPHONY_OUTBOUND_POOL",
        [{"number": "+918011223344", "provider": "plivo"}],
    )
    monkeypatch.setattr(
        "app.services.telephony.platform_outbound_pool.acquire_pool_slot",
        lambda _org_id: True,
    )

    number, used_pool, provider = resolve_outbound_from_number(db_session, org_id)
    assert number == "+918011223344"
    assert used_pool is True
    assert provider == "plivo"


def test_resolve_outbound_from_number_explicit_pool_number(
    clear_pool_settings, monkeypatch, db_session, org_id, seed_org
):
    monkeypatch.setattr(
        "app.services.telephony.platform_outbound_pool.settings.TELEPHONY_OUTBOUND_POOL",
        [{"number": "+918011223344", "provider": "plivo"}],
    )

    number, used_pool, provider = resolve_outbound_from_number(
        db_session,
        org_id,
        explicit_from_number="+918011223344",
    )
    assert number == "+918011223344"
    assert used_pool is True
    assert provider == "plivo"


def test_resolve_outbound_from_number_rejects_unknown_explicit_number(
    clear_pool_settings, db_session, org_id, seed_org
):
    with pytest.raises(ValueError, match="not registered"):
        resolve_outbound_from_number(
            db_session,
            org_id,
            explicit_from_number="+918099999999",
        )


def test_resolve_outbound_from_number_prefers_agent_plivo_over_older_vobiz(
    clear_pool_settings, db_session, org_id, seed_org
):
    from app.models.database import TelephonyIntegration, TelephonyPhoneNumber
    from app.models.enums import TelephonyProvider

    vobiz_integration = TelephonyIntegration(
        organization_id=org_id,
        provider=TelephonyProvider.VOBIZ.value,
        auth_id="vobiz-id",
        auth_token="vobiz-token",
        is_active=True,
        is_default=True,
    )
    plivo_integration = TelephonyIntegration(
        organization_id=org_id,
        provider=TelephonyProvider.PLIVO.value,
        auth_id="plivo-id",
        auth_token="plivo-token",
        is_active=True,
        is_default=True,
    )
    db_session.add_all([vobiz_integration, plivo_integration])
    db_session.flush()

    older_vobiz = TelephonyPhoneNumber(
        organization_id=org_id,
        telephony_integration_id=vobiz_integration.id,
        phone_number="+918011223300",
        is_active=True,
        inbound_enabled=True,
        outbound_enabled=True,
        source="imported",
    )
    agent_plivo = TelephonyPhoneNumber(
        organization_id=org_id,
        telephony_integration_id=plivo_integration.id,
        phone_number="+918011223399",
        is_active=True,
        inbound_enabled=True,
        outbound_enabled=True,
        source="imported",
    )
    db_session.add_all([older_vobiz, agent_plivo])
    db_session.commit()

    fallback_number, _, fallback_provider = resolve_outbound_from_number(db_session, org_id)
    assert fallback_number == "+918011223300"
    assert fallback_provider == "vobiz"

    number, used_pool, provider = resolve_outbound_from_number(
        db_session,
        org_id,
        preferred_from_number="+918011223399",
    )
    assert number == "+918011223399"
    assert used_pool is False
    assert provider == "plivo"
