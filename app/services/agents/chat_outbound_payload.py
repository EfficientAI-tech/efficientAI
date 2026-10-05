"""Shape outbound chat HTTP bodies (size + duplicate transcript policy)."""

from __future__ import annotations

from typing import Any, Optional

DEFAULT_MAX_OUTBOUND_MESSAGES = 40


def trim_transcript(
    transcript: list[dict[str, str]],
    *,
    max_messages: int = DEFAULT_MAX_OUTBOUND_MESSAGES,
) -> list[dict[str, str]]:
    if max_messages <= 0 or len(transcript) <= max_messages:
        return list(transcript)
    return list(transcript[-max_messages:])


def customer_api_request_body(
    config: dict[str, Any],
    *,
    openai_messages: list[dict[str, str]],
    transcript: list[dict[str, str]],
    agent_name: str,
    language: str,
) -> dict[str, Any]:
    """Customer API POST body: always messages; full transcript only when opted in."""
    body: dict[str, Any] = {
        "messages": openai_messages,
        "agent_name": agent_name,
        "language": language,
    }
    if config.get("include_full_transcript"):
        body["transcript"] = trim_transcript(transcript)
    return body


def messaging_webhook_request_body(
    *,
    transcript: list[dict[str, str]],
    channel: Any,
    sender_id: Any,
    max_messages: int = DEFAULT_MAX_OUTBOUND_MESSAGES,
) -> dict[str, Any]:
    trimmed = trim_transcript(transcript, max_messages=max_messages)
    last_user = ""
    for entry in reversed(trimmed):
        if (entry.get("speaker") or "").strip() == "Speaker 1":
            last_user = (entry.get("text") or "").strip()
            if last_user:
                break
    return {
        "messages": trimmed,
        "latest_user_message": last_user,
        "channel": channel,
        "sender_id": sender_id,
    }
