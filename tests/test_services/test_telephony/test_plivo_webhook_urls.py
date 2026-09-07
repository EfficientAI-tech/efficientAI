"""Tests for Plivo webhook URL helpers."""

import pytest

from app.services.telephony import plivo_webhook_urls


def test_plivo_answer_webhook_url_uses_provider_namespace(monkeypatch):
    monkeypatch.setattr(plivo_webhook_urls.settings, "PLIVO_WEBHOOK_BASE_URL", "https://public.example.com")
    monkeypatch.setattr(plivo_webhook_urls.settings, "API_V1_PREFIX", "/api/v1")

    assert (
        plivo_webhook_urls.plivo_answer_webhook_url()
        == "https://public.example.com/api/v1/telephony/plivo/webhooks/answer"
    )
    assert (
        plivo_webhook_urls.plivo_hangup_webhook_url()
        == "https://public.example.com/api/v1/telephony/plivo/webhooks/events"
    )


def test_legacy_answer_webhook_url_kept_for_exotel(monkeypatch):
    monkeypatch.setattr(plivo_webhook_urls.settings, "PLIVO_WEBHOOK_BASE_URL", "https://public.example.com")
    monkeypatch.setattr(plivo_webhook_urls.settings, "API_V1_PREFIX", "/api/v1")

    assert (
        plivo_webhook_urls.legacy_answer_webhook_url()
        == "https://public.example.com/api/v1/telephony/webhooks/answer"
    )


def test_plivo_webhook_base_requires_config(monkeypatch):
    monkeypatch.setattr(plivo_webhook_urls.settings, "PLIVO_WEBHOOK_BASE_URL", "")

    with pytest.raises(ValueError, match="Plivo webhook base URL is not configured"):
        plivo_webhook_urls.plivo_answer_webhook_url()
