"""Unit tests for Vobiz webhook signature helpers."""

import hmac
import hashlib

from app.services.telephony.webhook_signature_v1 import (
    compute_plivo_v1_webhook_signature,
    validate_plivo_v1_webhook_signature,
)
from app.services.telephony.webhook_signature_vobiz import validate_vobiz_raw_body_hmac_sha256


def test_vobiz_raw_body_hmac_hex():
    body = b"Event=Hangup&CallUUID=abc"
    secret = "test-token"
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert validate_vobiz_raw_body_hmac_sha256(body, secret, sig)


def test_plivo_v1_roundtrip():
    token = "auth"
    uri = "https://sandbox.example.com/api/v1/telephony/vobiz/webhooks/answer"
    params = {"CallUUID": "u", "To": "+919876543210"}
    sig = compute_plivo_v1_webhook_signature(token, uri, params)
    assert validate_plivo_v1_webhook_signature(token, uri, params, sig)
