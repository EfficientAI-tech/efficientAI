"""Plivo-compatible carrier webhook signature validation (V1/V2/V3)."""

from __future__ import annotations

from typing import Any, Dict, Mapping

from starlette.requests import Request

from app.services.telephony.webhook_signature_v1 import validate_plivo_v1_webhook_signature


def signature_headers_present(request: Request) -> bool:
    return bool(
        request.headers.get("X-Plivo-Signature-V3")
        or request.headers.get("X-Plivo-Signature-V2")
        or request.headers.get("X-Plivo-Signature")
        or request.headers.get("X-Vobiz-Signature")
    )


def validate_plivo_compatible_webhook_signature(
    request: Request,
    *,
    auth_token: str,
    uri: str,
    sign_params: Mapping[str, Any],
    method: str = "POST",
) -> bool:
    """Return True if the request matches any supported Plivo/Vobiz signature scheme."""
    if not auth_token:
        return False

    v3_sig = request.headers.get("X-Plivo-Signature-V3")
    v3_nonce = request.headers.get("X-Plivo-Signature-V3-Nonce")
    if v3_sig and v3_nonce:
        try:
            from plivo.utils.signature_v3 import validate_v3_signature

            if validate_v3_signature(
                method.upper(),
                uri,
                v3_nonce,
                auth_token,
                v3_sig,
                dict(sign_params),
            ):
                return True
        except Exception:
            pass

    v2_sig = request.headers.get("X-Plivo-Signature-V2")
    v2_nonce = request.headers.get("X-Plivo-Signature-V2-Nonce")
    if v2_sig and v2_nonce:
        try:
            from plivo.utils import validate_signature as validate_v2_signature

            if validate_v2_signature(uri, v2_nonce, v2_sig, auth_token):
                return True
        except Exception:
            pass

    v1_sig = request.headers.get("X-Plivo-Signature") or request.headers.get("X-Vobiz-Signature")
    if v1_sig and validate_plivo_v1_webhook_signature(auth_token, uri, sign_params, v1_sig):
        return True

    return False


def signature_header_names_for_log(request: Request) -> str:
    names = []
    for name in (
        "X-Plivo-Signature-V3",
        "X-Plivo-Signature-V3-Nonce",
        "X-Plivo-Signature-V2",
        "X-Plivo-Signature-V2-Nonce",
        "X-Plivo-Signature",
        "X-Vobiz-Signature",
    ):
        if request.headers.get(name):
            names.append(name)
    return ",".join(names) if names else "none"
