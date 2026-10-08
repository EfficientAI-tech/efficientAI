"""Public HTTPS callback URLs for Telnyx voice and SMS webhooks."""

from __future__ import annotations

from app.config import settings
from app.core.public_url import configured_public_base_url


def telnyx_webhook_base() -> str:
    explicit = (settings.TELNYX_WEBHOOK_BASE_URL or "").strip().rstrip("/")
    if explicit:
        return explicit
    fallback = configured_public_base_url().rstrip("/")
    if fallback:
        return fallback
    raise ValueError(
        "Telnyx webhook base URL is not configured. Set telnyx.webhook_base_url or "
        "security.public_base_url in config.yml."
    )


def _api_prefix() -> str:
    return (settings.API_V1_PREFIX or "/api/v1").rstrip("/")


def telnyx_voice_webhook_url() -> str:
    return f"{telnyx_webhook_base()}{_api_prefix()}/telephony/telnyx/webhooks/voice"


def telnyx_sms_inbound_webhook_url() -> str:
    return f"{telnyx_webhook_base()}{_api_prefix()}/telephony/telnyx/webhooks/sms-inbound"
