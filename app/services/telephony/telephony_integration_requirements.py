"""Required telephony integration fields per provider (messaging / webhooks)."""

from __future__ import annotations

import re
from typing import Any, Optional

from app.models.database import TelephonyIntegration
from app.models.enums import TelephonyProvider

_DIGITS = re.compile(r"^\d{8,20}$")


def _effective_field(
    data: dict[str, Any],
    integration: Optional[TelephonyIntegration],
    key: str,
) -> str:
    if key in data:
        return str(data.get(key) or "").strip()
    if integration is not None:
        return str(getattr(integration, key, None) or "").strip()
    return ""


def validate_telephony_integration_for_save(
    provider: str,
    data: dict[str, Any],
    *,
    integration: Optional[TelephonyIntegration] = None,
    is_create: bool = False,
) -> None:
    """Raise ValueError when provider-specific required fields are missing."""
    p = (provider or "").strip().lower()

    if p == TelephonyProvider.META_WHATSAPP.value:
        waba = _effective_field(data, integration, "voice_app_id")
        if not waba:
            raise ValueError(
                "WhatsApp Business Account ID (WABA) is required for Meta WhatsApp. "
                "Without it, Meta will not deliver inbound message webhooks to your app "
                "(subscribed_apps). Use the WABA id from Meta Business Settings."
            )
        if not _DIGITS.match(waba):
            raise ValueError("WABA id must be numeric (typically 15–20 digits).")

    if p == TelephonyProvider.TELNYX.value:
        public_key = _effective_field(data, integration, "verify_app_uuid")
        if is_create or "verify_app_uuid" in data:
            if not public_key:
                raise ValueError(
                    "Telnyx webhook public key is required for inbound SMS webhooks. "
                    "Paste the Ed25519 public key from Telnyx Mission Control (verify_app_uuid field)."
                )

    if p == TelephonyProvider.TWILIO.value and is_create:
        if not _effective_field(data, integration, "auth_id"):
            raise ValueError("Twilio Account SID (auth_id) is required.")
        if not _effective_field(data, integration, "auth_token"):
            raise ValueError("Twilio Auth Token (auth_token) is required.")
