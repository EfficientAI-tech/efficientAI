"""Meta WhatsApp webhook signature verification."""

import hashlib
import hmac

from app.services.telephony.meta_whatsapp_webhook_verify import verify_meta_whatsapp_signature


def test_verify_meta_whatsapp_signature_valid():
    secret = "test-app-secret"
    body = b'{"object":"whatsapp_business_account"}'
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_meta_whatsapp_signature(body, sig, secret)


def test_verify_meta_whatsapp_signature_rejects_wrong_secret():
    body = b'{"object":"whatsapp_business_account"}'
    sig = "sha256=" + hmac.new(b"other", body, hashlib.sha256).hexdigest()
    assert not verify_meta_whatsapp_signature(body, sig, "test-app-secret")
