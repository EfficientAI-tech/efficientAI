"""Public HTTPS callback URLs for Twilio SMS webhooks (chat eval inbound)."""

from __future__ import annotations

from app.config import settings
from app.core.public_url import configured_public_base_url


def twilio_webhook_base() -> str:
    """Public API base for Twilio SMS inbound (ngrok or prod API host).

    Prefer ``twilio.webhook_base_url`` in config.yml (same idea as ``vobiz.webhook_base_url``).
    Falls back to ``security.public_base_url`` / ``PUBLIC_BASE_URL``, then ``app.frontend_base_url``.
    """
    explicit = (settings.TWILIO_WEBHOOK_BASE_URL or "").strip().rstrip("/")
    if explicit:
        return explicit
    fallback = configured_public_base_url().rstrip("/")
    if fallback:
        return fallback
    raise ValueError(
        "Twilio webhook base URL is not configured. Set twilio.webhook_base_url or "
        "security.public_base_url in config.yml (e.g. your ngrok https URL for API port 8000)."
    )


def twilio_sms_inbound_webhook_url() -> str:
    prefix = (settings.API_V1_PREFIX or "/api/v1").rstrip("/")
    return f"{twilio_webhook_base()}{prefix}/telephony/twilio/webhooks/sms-inbound"


def twilio_voice_webhook_url() -> str:
    prefix = (settings.API_V1_PREFIX or "/api/v1").rstrip("/")
    return f"{twilio_webhook_base()}{prefix}/telephony/twilio/webhooks/voice-inbound"
