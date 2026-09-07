"""Tests for media / telephony URL helpers."""

from app.config import settings
from app.services.telephony.vobiz_agent_context import build_carrier_ws_url


def test_build_carrier_ws_url_uses_webhook_base_when_media_ws_unset(monkeypatch):
    monkeypatch.setattr(settings, "MEDIA_WS_BASE_URL", "")
    monkeypatch.setattr(settings, "VOBIZ_WEBHOOK_BASE_URL", "https://telephony.example.com")

    url = build_carrier_ws_url(agent_id="abc", session="sess-1")
    assert url.startswith("wss://telephony.example.com/api/v1/telephony/carrier/ws?")
    assert "agent_id=abc" in url
    assert "session=sess-1" in url


def test_build_carrier_ws_url_prefers_explicit_media_ws_base(monkeypatch):
    monkeypatch.setattr(settings, "MEDIA_WS_BASE_URL", "wss://media.example.com")
    monkeypatch.setattr(settings, "VOBIZ_WEBHOOK_BASE_URL", "https://telephony.example.com")

    url = build_carrier_ws_url(agent_id="abc", session="sess-1")
    assert url.startswith("wss://media.example.com/api/v1/telephony/carrier/ws?")
