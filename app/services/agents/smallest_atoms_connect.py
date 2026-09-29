"""Smallest Atoms text chat session credentials (LiveKit, same as atoms-client-sdk)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger


@dataclass(frozen=True)
class SmallestChatCredentials:
    host: str
    access_token: str
    conversation_id: str | None = None
    call_id: str | None = None


def _token_from_payload(data: dict[str, Any]) -> str | None:
    for key in ("access_token", "accessToken", "token"):
        raw = data.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


def _host_from_payload(data: dict[str, Any]) -> str | None:
    raw = data.get("host") or data.get("wsUrl") or data.get("ws_url")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _ids_from_payload(data: dict[str, Any]) -> tuple[str | None, str | None]:
    call_id = data.get("callId") or data.get("call_id") or data.get("id")
    conv_id = data.get("conversationId") or data.get("conversation_id")
    call_s = str(call_id).strip() if call_id else None
    conv_s = str(conv_id).strip() if conv_id else None
    return call_s, conv_s


def _credentials_from_response(data: dict[str, Any]) -> SmallestChatCredentials | None:
    host = _host_from_payload(data)
    token = _token_from_payload(data)
    if not host or not token:
        return None
    call_id, conversation_id = _ids_from_payload(data)
    return SmallestChatCredentials(
        host=host,
        access_token=token,
        call_id=call_id,
        conversation_id=conversation_id or call_id,
    )


def resolve_chat_credentials(api_key: str, agent_id: str) -> SmallestChatCredentials:
    """Mint LiveKit host + JWT for Smallest text (chat) mode."""
    from app.services.voice_providers.smallest import SmallestVoiceProvider

    provider = SmallestVoiceProvider(api_key)
    agent_id = agent_id.strip()
    attempts: list[tuple[str, dict[str, Any]]] = [
        ("/conversation/register-call", {"agentId": agent_id, "mode": "chat"}),
        ("/conversation/chat", {"agentId": agent_id}),
        ("/conversation/register-call", {"agentId": agent_id, "mode": "text"}),
    ]
    errors: list[str] = []
    for path, payload in attempts:
        try:
            data = provider._request("POST", path, json=payload, timeout=45.0)
        except Exception as exc:
            errors.append(f"{path}: {exc}")
            continue
        creds = _credentials_from_response(data)
        if creds:
            logger.debug(
                "Smallest chat credentials via {} (host={}, call_id={})",
                path,
                creds.host,
                creds.call_id,
            )
            return creds
        errors.append(f"{path}: missing host or token (keys={list(data.keys())})")

    detail = "; ".join(errors) if errors else "no endpoints tried"
    raise ValueError(
        "Smallest chat session could not be created — need host + access token from "
        f"register-call/chat API ({detail})"
    )


def parse_inbound_event(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        import json

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.debug("Smallest chat non-JSON frame: {!r}", raw[:200])
            return None
    else:
        parsed = raw
    if isinstance(parsed, dict):
        if parsed.get("type"):
            return parsed
        nested = parsed.get("event") or parsed.get("data") or parsed.get("payload")
        if isinstance(nested, dict) and nested.get("type"):
            return nested
        return parsed if parsed.get("type") else None
    return None
