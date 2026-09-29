"""SSRF checks for user-configured chat / messaging HTTP endpoints."""

from __future__ import annotations

from typing import Any, Optional

from app.services.telephony.recording_download import assert_outbound_http_url_safe

_URL_KEYS = (
    "api_base_url",
    "outbound_webhook_url",
    "messaging_webhook_url",
    "messaging_sync_reply_url",
)


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
        if url:
            assert_outbound_http_url_safe(url, allow_loopback=allow_loopback)
