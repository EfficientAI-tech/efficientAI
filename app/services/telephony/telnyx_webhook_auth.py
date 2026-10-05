"""Telnyx webhook Ed25519 signature verification."""

from __future__ import annotations

import base64
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def verify_telnyx_webhook_signature(
    *,
    public_key_b64: str,
    signature_b64: str,
    timestamp: str,
    raw_body: bytes,
    max_age_secs: int = 300,
) -> bool:
    key_text = (public_key_b64 or "").strip()
    sig_text = (signature_b64 or "").strip()
    ts_text = (timestamp or "").strip()
    if not key_text or not sig_text or not ts_text or not raw_body:
        return False
    try:
        ts_int = int(ts_text)
    except ValueError:
        return False
    if abs(time.time() - ts_int) > max_age_secs:
        return False
    try:
        public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(key_text))
        signature = base64.b64decode(sig_text)
        signed = f"{ts_text}|".encode("utf-8") + raw_body
        public_key.verify(signature, signed)
        return True
    except (InvalidSignature, ValueError):
        return False
