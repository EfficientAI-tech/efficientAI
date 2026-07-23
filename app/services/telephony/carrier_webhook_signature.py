"""Plivo-compatible carrier webhook signature validation (V1/V2/V3)."""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from starlette.requests import Request

from app.services.telephony.webhook_signature_v1 import validate_plivo_v1_webhook_signature
from app.services.telephony.webhook_signature_vobiz import validate_vobiz_raw_body_hmac_sha256


def _first_header(request: Request, *names: str) -> Optional[str]:
    for name in names:
        value = request.headers.get(name)
        if value:
            return value
    return None


def signature_headers_present(request: Request) -> bool:
    return bool(
        _first_header(
            request,
            "X-Plivo-Signature-V3",
            "X-Vobiz-Signature-V3",
            "X-Plivo-Signature-V2",
            "X-Vobiz-Signature-V2",
            "X-Plivo-Signature",
            "X-Vobiz-Signature",
        )
    )


def _webhook_raw_body(request: Request) -> bytes:
    raw = getattr(request.state, "webhook_raw_body", None)
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw)
    return b""


def validate_plivo_compatible_webhook_signature(
    request: Request,
    *,
    auth_token: str,
    uri: str,
    sign_params: Mapping[str, Any],
    method: str = "POST",
    extra_secrets: Sequence[str] = (),
) -> bool:
    """Return True if the request matches any supported Plivo/Vobiz signature scheme."""
    if not auth_token:
        return False

    secrets = [auth_token, *[s for s in extra_secrets if s and s != auth_token]]

    v3_sig = _first_header(
        request,
        "X-Plivo-Signature-V3",
        "X-Vobiz-Signature-V3",
        "X-Vobiz-Signature-Ma-V3",
    )
    v3_nonce = _first_header(
        request,
        "X-Plivo-Signature-V3-Nonce",
        "X-Vobiz-Signature-V3-Nonce",
        "X-Vobiz-Signature-Ma-V3-Nonce",
    )
    if v3_sig and v3_nonce:
        try:
            from plivo.utils.signature_v3 import validate_v3_signature

            for secret in secrets:
                if validate_v3_signature(
                    method.upper(),
                    uri,
                    v3_nonce,
                    secret,
                    v3_sig,
                    dict(sign_params),
                ):
                    return True
        except Exception:
            pass

    v2_sig = _first_header(
        request,
        "X-Plivo-Signature-V2",
        "X-Vobiz-Signature-V2",
        "X-Vobiz-Signature-Ma-V2",
    )
    v2_nonce = _first_header(
        request,
        "X-Plivo-Signature-V2-Nonce",
        "X-Vobiz-Signature-V2-Nonce",
        "X-Vobiz-Signature-Ma-V2-Nonce",
    )
    if v2_sig and v2_nonce:
        try:
            from plivo.utils import validate_signature as validate_v2_signature

            for secret in secrets:
                if validate_v2_signature(uri, v2_nonce, v2_sig, secret):
                    return True
        except Exception:
            pass

    v1_sig = _first_header(request, "X-Plivo-Signature", "X-Vobiz-Signature")
    if v1_sig:
        for secret in secrets:
            if validate_plivo_v1_webhook_signature(secret, uri, sign_params, v1_sig):
                return True
        raw_body = _webhook_raw_body(request)
        if raw_body:
            for secret in secrets:
                if validate_vobiz_raw_body_hmac_sha256(raw_body, secret, v1_sig):
                    return True

    return False


def signature_header_names_for_log(request: Request) -> str:
    names = []
    for name in (
        "X-Plivo-Signature-V3",
        "X-Plivo-Signature-V3-Nonce",
        "X-Vobiz-Signature-V3",
        "X-Vobiz-Signature-V3-Nonce",
        "X-Plivo-Signature-V2",
        "X-Plivo-Signature-V2-Nonce",
        "X-Vobiz-Signature-V2",
        "X-Vobiz-Signature-V2-Nonce",
        "X-Plivo-Signature",
        "X-Vobiz-Signature",
    ):
        if request.headers.get(name):
            names.append(name)
    return ",".join(names) if names else "none"
