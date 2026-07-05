"""Vobiz XML builders for webhook responses (Plivo-compatible markup)."""

from xml.sax.saxutils import escape


def stream_to_agent(ws_url: str, *, record_action_url: str | None = None) -> str:
    """Return XML that connects the call to a bidirectional media WebSocket."""
    safe_ws_url = escape(ws_url, {'"': '&quot;', "'": '&apos;'})
    parts = ['<?xml version="1.0" encoding="UTF-8"?>', "<Response>"]
    parts.append(
        (
            '<Stream bidirectional="true" keepCallAlive="true" '
            'contentType="audio/x-mulaw;rate=8000">'
            f"{safe_ws_url}</Stream>"
        )
    )
    if record_action_url:
        safe_record_url = escape(record_action_url, {'"': '&quot;', "'": '&apos;'})
        parts.append(
            (
                f'<Record action="{safe_record_url}" recordSession="true" '
                'maxLength="3600" fileFormat="mp3" />'
            )
        )
    parts.append("</Response>")
    return "".join(parts)


def speak_and_hangup(message: str) -> str:
    """Build XML to speak a message and hang up."""
    safe_message = escape(message)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f"<Speak>{safe_message}</Speak>"
        "<Hangup />"
        "</Response>"
    )


def reject_call(reason: str = "This number is not available.") -> str:
    """Build XML to reject a call with a spoken message."""
    return speak_and_hangup(reason)
