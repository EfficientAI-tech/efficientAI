"""Verify Meta WhatsApp Cloud webhook POST signatures (X-Hub-Signature-256)."""

from __future__ import annotations

import hashlib
import hmac


def verify_meta_whatsapp_signature(
    raw_body: bytes,
    signature_header: str | None,
    app_secret: str,
) -> bool:
    secret = (app_secret or "").strip()
    if not secret:
        return False
    if not signature_header:
        return False
    received = signature_header.strip()
    if received.startswith("sha256="):
        received = received[7:]
    expected = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, received)
