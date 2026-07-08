"""Tests for Exotel client helpers."""

import pytest

from app.services.telephony.exotel_client import (
    DEFAULT_API_BASE,
    build_exotel_client_from_integration,
    is_exotel_rest_api_host,
    resolve_exotel_api_base,
    validate_exotel_api_host_for_save,
)


def test_resolve_exotel_api_base_prefers_integration_api_host(monkeypatch):
    monkeypatch.setattr(
        "app.services.telephony.exotel_client.settings",
        type("SettingsStub", (), {"EXOTEL_API_BASE": "https://api.exotel.com"})(),
    )
    assert (
        resolve_exotel_api_base("api.in.exotel.com")
        == "https://api.in.exotel.com"
    )
    assert (
        resolve_exotel_api_base("https://api.in.exotel.com/")
        == "https://api.in.exotel.com"
    )


def test_resolve_exotel_api_base_falls_back_to_default(monkeypatch):
    monkeypatch.setattr(
        "app.services.telephony.exotel_client.settings",
        type("SettingsStub", (), {})(),
    )
    assert resolve_exotel_api_base(None) == DEFAULT_API_BASE
    assert resolve_exotel_api_base("") == DEFAULT_API_BASE


def test_resolve_exotel_api_base_uses_config_when_no_integration_host(monkeypatch):
    monkeypatch.setattr(
        "app.services.telephony.exotel_client.settings",
        type(
            "SettingsStub",
            (),
            {"EXOTEL_API_BASE": "https://api.in.exotel.com"},
        )(),
    )
    assert resolve_exotel_api_base(None) == "https://api.in.exotel.com"


def test_build_exotel_client_from_integration_uses_api_host():
    client = build_exotel_client_from_integration(
        auth_id="key",
        auth_token="token",
        account_sid="acct",
        api_host="api.in.exotel.com",
    )
    assert client._api_base == "https://api.in.exotel.com"


def test_is_exotel_rest_api_host_rejects_sip_domains():
    assert is_exotel_rest_api_host("api.exotel.com") is True
    assert is_exotel_rest_api_host("https://api.in.exotel.com/") is True
    assert is_exotel_rest_api_host("sip.exotel.com") is False
    assert is_exotel_rest_api_host("pbx.example.com") is False


def test_resolve_exotel_api_base_ignores_sip_domain_host(monkeypatch):
    monkeypatch.setattr(
        "app.services.telephony.exotel_client.settings",
        type(
            "SettingsStub",
            (),
            {"EXOTEL_API_BASE": "https://api.in.exotel.com"},
        )(),
    )
    assert resolve_exotel_api_base("sip.exotel.com") == "https://api.in.exotel.com"
    assert resolve_exotel_api_base("pbx.customer.example") == "https://api.in.exotel.com"


def test_validate_exotel_api_host_for_save_rejects_sip_domain():
    with pytest.raises(ValueError, match="REST API base"):
        validate_exotel_api_host_for_save("sip.exotel.com")
