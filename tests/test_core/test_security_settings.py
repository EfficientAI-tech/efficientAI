"""Trusted host and CSP finalize helpers."""

from app.config import settings
from app.core.security_settings import build_csp_policy_with_extras, resolve_trusted_hosts


def test_resolve_trusted_hosts_from_frontend_url(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_HOSTS_AUTO_FROM_FRONTEND", True)
    monkeypatch.setattr(settings, "FRONTEND_BASE_URL", "https://app.acme.com")
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "")
    monkeypatch.setattr(settings, "TRUSTED_HOSTS_EXPLICIT", ["extra.acme.com"])
    hosts = resolve_trusted_hosts()
    assert "app.acme.com" in hosts
    assert "*.acme.com" in hosts
    assert "extra.acme.com" in hosts


def test_default_csp_policy_includes_voice_providers():
    assert "https://api.vapi.ai" in settings.CSP_POLICY
    assert "https://*.daily.co" in settings.CSP_POLICY


def test_build_csp_policy_with_extras_merges_custom_host(monkeypatch):
    monkeypatch.setattr(settings, "CSP_CONNECT_SRC_EXTRA", ["https://api.custom.example"])
    monkeypatch.setattr(settings, "CSP_FRAME_SRC_EXTRA", [])
    monkeypatch.setattr(settings, "CSP_SCRIPT_SRC_EXTRA", [])
    policy = build_csp_policy_with_extras()
    assert "https://api.custom.example" in policy
    assert "https://api.vapi.ai" in policy
