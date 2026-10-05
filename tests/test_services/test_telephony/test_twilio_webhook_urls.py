from app.config import settings
from app.services.telephony import twilio_webhook_urls


def test_twilio_sms_inbound_url_uses_explicit_base(monkeypatch):
    monkeypatch.setattr(settings, "TWILIO_WEBHOOK_BASE_URL", "https://api.example.com", raising=False)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://ignored.example.com", raising=False)
    assert (
        twilio_webhook_urls.twilio_sms_inbound_webhook_url()
        == "https://api.example.com/api/v1/telephony/twilio/webhooks/sms-inbound"
    )


def test_twilio_webhook_base_falls_back_to_public_base(monkeypatch):
    monkeypatch.setattr(settings, "TWILIO_WEBHOOK_BASE_URL", "", raising=False)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://public.example.com", raising=False)
    assert twilio_webhook_urls.twilio_webhook_base() == "https://public.example.com"


def test_twilio_voice_inbound_url(monkeypatch):
    monkeypatch.setattr(settings, "TWILIO_WEBHOOK_BASE_URL", "https://api.example.com", raising=False)
    assert (
        twilio_webhook_urls.twilio_voice_webhook_url()
        == "https://api.example.com/api/v1/telephony/twilio/webhooks/voice-inbound"
    )
