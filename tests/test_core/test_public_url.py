"""Configured public URL helpers."""

from app.config import settings
from app.core.public_url import configured_public_base_url, configured_public_origin


def test_configured_public_base_url_prefers_public_base(monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://api.example.com")
    monkeypatch.setattr(settings, "FRONTEND_BASE_URL", "https://app.example.com")
    assert configured_public_base_url() == "https://api.example.com"


def test_configured_public_origin(monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "")
    monkeypatch.setattr(settings, "FRONTEND_BASE_URL", "https://sandbox.efficientai.cloud")
    assert configured_public_origin() == "https://sandbox.efficientai.cloud"
