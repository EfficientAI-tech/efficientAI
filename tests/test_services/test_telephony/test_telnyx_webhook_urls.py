from app.config import settings
from app.services.telephony.telnyx_webhook_urls import (
    telnyx_sms_inbound_webhook_url,
    telnyx_voice_webhook_url,
)


def test_telnyx_webhook_urls_use_config_base(monkeypatch):
    monkeypatch.setattr(settings, "TELNYX_WEBHOOK_BASE_URL", "https://api.example.com", raising=False)
    assert telnyx_sms_inbound_webhook_url().endswith("/telephony/telnyx/webhooks/sms-inbound")
    assert telnyx_voice_webhook_url().endswith("/telephony/telnyx/webhooks/voice")
