"""Twilio TwiML builders for Media Streams."""

from __future__ import annotations

import xml.sax.saxutils as saxutils


def stream_to_agent(ws_url: str) -> str:
    safe_url = saxutils.escape(ws_url, {'"': "&quot;"})
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        "<Connect>"
        f'<Stream url="{safe_url}"/>'
        "</Connect>"
        "</Response>"
    )
