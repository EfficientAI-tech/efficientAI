import base64
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.services.telephony.telnyx_webhook_auth import verify_telnyx_webhook_signature


def test_verify_telnyx_webhook_signature_roundtrip():
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    public_b64 = base64.b64encode(public_key.public_bytes_raw()).decode()
    body = b'{"data":{"event_type":"message.received"}}'
    ts = str(int(time.time()))
    signed = f"{ts}|".encode("utf-8") + body
    signature = base64.b64encode(private_key.sign(signed)).decode()
    assert verify_telnyx_webhook_signature(
        public_key_b64=public_b64,
        signature_b64=signature,
        timestamp=ts,
        raw_body=body,
    )
