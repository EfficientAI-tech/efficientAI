"""Vobiz-specific webhook signature helpers (beyond Plivo V1)."""

from __future__ import annotations

import base64
import hashlib
import hmac


def validate_vobiz_raw_body_hmac_sha256(
    raw_body: bytes,
    secret: str,
    signature: str,
) -> bool:
    """HMAC-SHA256 over exact request bytes (hex digest, per Vobiz trunk/messaging docs)."""
    if not raw_body or not secret or not signature:
        return False
    sig = signature.strip()
    mac = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256)
    expected_hex = mac.hexdigest()
    if hmac.compare_digest(expected_hex, sig.lower()):
        return True
    expected_b64 = base64.b64encode(mac.digest()).decode("utf-8")
    return hmac.compare_digest(expected_b64, sig)
