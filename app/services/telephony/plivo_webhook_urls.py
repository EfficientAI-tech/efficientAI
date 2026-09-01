"""Public HTTPS callback URLs for native Plivo telephony webhooks."""

from __future__ import annotations

from app.config import settings


def plivo_webhook_base() -> str:
    base = (settings.PLIVO_WEBHOOK_BASE_URL or "").strip().rstrip("/")
    if not base:
        raise ValueError(
            "Plivo webhook base URL is not configured. Set plivo.webhook_base_url in platform config."
        )
    return base


def plivo_answer_webhook_url() -> str:
    return f"{plivo_webhook_base()}{settings.API_V1_PREFIX}/telephony/plivo/webhooks/answer"


def plivo_hangup_webhook_url() -> str:
    return f"{plivo_webhook_base()}{settings.API_V1_PREFIX}/telephony/plivo/webhooks/events"


def plivo_masking_webhook_url() -> str:
    return f"{plivo_webhook_base()}{settings.API_V1_PREFIX}/telephony/plivo/webhooks/masking"


def legacy_answer_webhook_url() -> str:
    """Legacy generic path kept for Exotel and already-imported Plivo numbers."""
    return f"{plivo_webhook_base()}{settings.API_V1_PREFIX}/telephony/webhooks/answer"


def legacy_events_webhook_url() -> str:
    return f"{plivo_webhook_base()}{settings.API_V1_PREFIX}/telephony/webhooks/events"
