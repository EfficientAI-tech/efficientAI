"""Plivo V1 voice webhook signing (HMAC-SHA1). Shared by Plivo/Vobiz carriers and dev tools."""

from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Any, Dict, Mapping


def compute_plivo_v1_webhook_signature(
    auth_token: str,
    uri: str,
    params: Mapping[str, Any],
) -> str:
    nonce = uri
    for key in sorted(params.keys()):
        nonce += key + str(params[key])
    digest = hmac.new(auth_token.encode("utf-8"), nonce.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("utf-8")


def validate_plivo_v1_webhook_signature(
    auth_token: str,
    uri: str,
    params: Mapping[str, Any],
    signature: str,
) -> bool:
    if not auth_token or not signature:
        return False
    expected = compute_plivo_v1_webhook_signature(auth_token, uri, params)
    return hmac.compare_digest(expected, signature.strip())
