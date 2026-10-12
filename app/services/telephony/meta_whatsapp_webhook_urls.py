"""Public HTTPS callback URLs for Meta WhatsApp Cloud webhooks (chat eval inbound)."""

from __future__ import annotations

from app.config import settings
from app.core.public_url import configured_public_base_url


def meta_whatsapp_webhook_base() -> str:
    explicit = (settings.META_WHATSAPP_WEBHOOK_BASE_URL or "").strip().rstrip("/")
    if explicit:
        return explicit
    fallback = configured_public_base_url().rstrip("/")
    if fallback:
        return fallback
    raise ValueError(
        "Meta WhatsApp webhook base URL is not configured. Set meta_whatsapp.webhook_base_url or "
        "security.public_base_url in config.yml (e.g. your ngrok https URL for API port 8000)."
    )


def meta_whatsapp_inbound_webhook_url() -> str:
    prefix = (settings.API_V1_PREFIX or "/api/v1").rstrip("/")
    return f"{meta_whatsapp_webhook_base()}{prefix}/chat/messaging/meta/whatsapp-inbound"
