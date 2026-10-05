"""SSRF checks for user-configured chat / messaging HTTP endpoints."""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlparse

from app.services.telephony.recording_download import ExotelInvalidContentError, assert_outbound_http_url_safe

_URL_KEYS = (
    "api_base_url",
    "outbound_webhook_url",
    "messaging_webhook_url",
    "messaging_sync_reply_url",
    "websocket_url",
)


def assert_websocket_url_safe(url: str, *, allow_loopback: bool = False) -> None:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"ws", "wss"}:
        raise ExotelInvalidContentError(
            f"WebSocket URL must use ws or wss, got {parsed.scheme or 'none'}"
        )
    if not parsed.hostname:
        raise ExotelInvalidContentError("WebSocket URL is missing a hostname")
    http_equiv = url.strip().replace("wss://", "https://", 1).replace("ws://", "http://", 1)
    assert_outbound_http_url_safe(http_equiv, allow_loopback=allow_loopback)


def assert_chat_connection_urls_safe(
    config: Optional[dict[str, Any]],
    *,
    allow_loopback: bool = False,
) -> None:
    if not config or not isinstance(config, dict):
        return
    for key in _URL_KEYS:
        raw = config.get(key)
        if not isinstance(raw, str):
            continue
        url = raw.strip()
        if not url:
            continue
        if key == "websocket_url":
            assert_websocket_url_safe(url, allow_loopback=allow_loopback)
        else:
            assert_outbound_http_url_safe(url, allow_loopback=allow_loopback)
