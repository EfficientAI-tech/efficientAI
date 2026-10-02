"""Helpers to read Telnyx fields from TelephonyIntegration rows."""

from __future__ import annotations

from typing import Optional

from app.core.encryption import decrypt_api_key
from app.models.database import TelephonyIntegration


def telnyx_api_key(integration: TelephonyIntegration) -> str:
    return decrypt_api_key(integration.auth_token).strip()


def telnyx_messaging_profile_id(integration: TelephonyIntegration) -> Optional[str]:
    raw = (integration.voice_app_id or "").strip()
    return raw or None


def telnyx_webhook_public_key(integration: TelephonyIntegration) -> str:
    return (integration.verify_app_uuid or "").strip()
