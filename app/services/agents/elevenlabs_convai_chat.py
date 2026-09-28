"""Synchronous text turns against ElevenLabs ConvAI WebSocket."""

from __future__ import annotations

import json
from typing import Any, Optional

import websockets.sync.client


def _extract_agent_text_from_event(event: dict[str, Any]) -> Optional[str]:
    etype = str(event.get("type") or "")
    if etype in ("agent_response", "agent_response_event"):
        payload = event.get("agent_response_event") or event
        text = payload.get("agent_response") or payload.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
    if etype == "agent_response_correction":
        payload = event.get("agent_response_correction_event") or event
        corrected = payload.get("corrected_agent_response")
        if isinstance(corrected, str) and corrected.strip():
            return corrected.strip()
    if etype == "agent_chat_response_part":
        part = event.get("text_response_part") or event.get("agent_chat_response_part") or event
        if isinstance(part, dict):
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
        text = event.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
    return None


def _handle_ping(ws: Any, event: dict[str, Any]) -> None:
    ping_event = event.get("ping_event")
    if not isinstance(ping_event, dict):
        return
    event_id = ping_event.get("event_id")
    if event_id is None:
        return
    ws.send(json.dumps({"type": "pong", "event_id": event_id}))


def elevenlabs_convai_reply(
    api_key: str,
    agent_id: str,
    user_text: str,
    *,
    conversation_id: Optional[str] = None,
    timeout: float = 90.0,
) -> tuple[str, Optional[str]]:
    query = f"agent_id={agent_id}"
    if conversation_id:
        query += f"&conversation_id={conversation_id}"
    uri = f"wss://api.elevenlabs.io/v1/convai/conversation?{query}"
    headers = {"xi-api-key": api_key}

    user_text = (user_text or "").strip()
    if not user_text:
        raise ValueError("ElevenLabs convai requires a non-empty user message")

    reply_parts: list[str] = []
    new_conversation_id = conversation_id

    with websockets.sync.client.connect(
        uri,
        additional_headers=headers,
        open_timeout=timeout,
        close_timeout=5,
        ping_interval=None,
    ) as ws:
        init = {
            "type": "conversation_initiation_client_data",
            "conversation_config_override": {
                "conversation": {"text_only": True},
            },
        }
        ws.send(json.dumps(init))
        ws.send(json.dumps({"type": "user_message", "text": user_text}))

        while True:
            raw = ws.recv(timeout=timeout)
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue

            etype = str(event.get("type") or "")
            if etype == "ping":
                _handle_ping(ws, event)
                continue

            if etype == "conversation_initiation_metadata":
                meta = event.get("conversation_initiation_metadata_event") or event.get(
                    "conversation_initiation_metadata"
                )
                if isinstance(meta, dict):
                    cid = meta.get("conversation_id")
                    if isinstance(cid, str) and cid.strip():
                        new_conversation_id = cid.strip()
                continue

            chunk = _extract_agent_text_from_event(event)
            if chunk:
                reply_parts.append(chunk)

            if etype in ("agent_response_correction",):
                reply_parts = [chunk] if chunk else reply_parts

            if etype in (
                "agent_response",
                "agent_response_end",
                "agent_chat_response_part_end",
            ):
                if reply_parts:
                    break

            if etype == "error":
                msg = event.get("message") or event.get("error")
                raise ValueError(f"ElevenLabs convai error: {msg or event}")

    combined = " ".join(reply_parts).strip()
    if not combined:
        raise ValueError("ElevenLabs convai returned an empty assistant message")
    return combined, new_conversation_id
