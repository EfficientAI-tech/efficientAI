"""Tests for media / telephony URL helpers."""

from starlette.requests import Request

from app.config import settings
from app.services.media_urls import cross_host_voice_ws, resolve_voice_agent_ws_base
from app.services.telephony.vobiz_agent_context import build_carrier_ws_url


def test_cross_host_voice_ws_detects_different_hostname():
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/voice-agent/connect",
        "headers": [(b"host", b"api.example.com")],
        "query_string": b"",
        "server": ("api.example.com", 443),
        "client": ("127.0.0.1", 12345),
        "scheme": "https",
        "root_path": "",
    }
    request = Request(scope)

    assert cross_host_voice_ws("wss://media.example.com", request) is True
    assert cross_host_voice_ws("wss://api.example.com", request) is False


def test_resolve_voice_agent_ws_base_prefers_media_ws(monkeypatch):
    monkeypatch.setattr(settings, "MEDIA_WS_BASE_URL", "wss://media.example.com")
    assert resolve_voice_agent_ws_base() == "wss://media.example.com"


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
