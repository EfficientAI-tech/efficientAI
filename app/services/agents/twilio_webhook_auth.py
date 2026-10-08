"""Validate Twilio webhook HTTP signatures."""

from __future__ import annotations

import base64
import hmac
import hashlib
from typing import Mapping
from urllib.parse import urlparse, urlunparse


def _compare_digest(expected: str, actual: str) -> bool:
    return hmac.compare_digest(expected.encode("utf-8"), actual.encode("utf-8"))


def compute_twilio_signature(
    auth_token: str,
    url: str,
    params: Mapping[str, str],
) -> str:
    data = url
    for key in sorted(params.keys()):
        data += key + params[key]
    digest = hmac.new(
        auth_token.encode("utf-8"),
        data.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def validate_twilio_request(
    *,
    auth_token: str,
    url: str,
    params: Mapping[str, str],
    signature: str,
) -> bool:
    if not auth_token or not signature:
        return False
    expected = compute_twilio_signature(auth_token, url, params)
    return _compare_digest(expected, signature)


def public_webhook_url_for_validation(request_url: str, public_base: str) -> str:
    """Twilio signs the public URL; replace internal host when behind a proxy."""
    public_base = (public_base or "").strip().rstrip("/")
    if not public_base:
        return request_url
    parsed_req = urlparse(request_url)
    parsed_pub = urlparse(public_base if "://" in public_base else f"https://{public_base}")
    scheme = parsed_pub.scheme or parsed_req.scheme or "https"
    netloc = parsed_pub.netloc or parsed_req.netloc
    path = parsed_req.path
    query = parsed_req.query
    return urlunparse((scheme, netloc, path, "", query, ""))
