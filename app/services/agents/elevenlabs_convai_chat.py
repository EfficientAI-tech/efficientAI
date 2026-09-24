"""Synchronous text turns against ElevenLabs ConvAI WebSocket."""

from __future__ import annotations

import json
from typing import Any, Optional

import websockets.sync.client


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

    reply_parts: list[str] = []
    new_conversation_id = conversation_id

    with websockets.sync.client.connect(
        uri,
        additional_headers=headers,
        open_timeout=timeout,
        close_timeout=5,
    ) as ws:
        init = {
            "type": "conversation_initiation_client_data",
            "conversation_config_override": {"conversation": {"text_only": True}},
        }
        ws.send(json.dumps(init))

        deadline = timeout
        user_sent = False
        while True:
            raw = ws.recv(timeout=deadline)
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue

            etype = str(event.get("type") or "")
            if etype == "conversation_initiation_metadata":
                meta = event.get("conversation_initiation_metadata_event") or event.get(
                    "conversation_initiation_metadata"
                )
                if isinstance(meta, dict):
                    cid = meta.get("conversation_id")
                    if isinstance(cid, str) and cid.strip():
                        new_conversation_id = cid.strip()

            if not user_sent and user_text.strip():
                ws.send(json.dumps({"type": "user_message", "text": user_text.strip()}))
                user_sent = True
                continue

            if etype in ("agent_response", "agent_response_event"):
                payload = event.get("agent_response_event") or event
                text = payload.get("agent_response") or payload.get("text")
                if isinstance(text, str) and text.strip():
                    reply_parts.append(text.strip())
            elif etype == "agent_chat_response_part":
                part = event.get("text") or event.get("agent_chat_response_part")
                if isinstance(part, str) and part.strip():
                    reply_parts.append(part.strip())
            elif etype in ("agent_response_correction",):
                continue
            elif etype in ("ping", "internal_tentative_agent_response"):
                continue
            elif etype in ("agent_response_end", "agent_chat_response_part_end"):
                if reply_parts:
                    break
            elif etype == "error":
                msg = event.get("message") or event.get("error")
                raise ValueError(f"ElevenLabs convai error: {msg or event}")

    combined = " ".join(reply_parts).strip()
    if not combined:
        raise ValueError("ElevenLabs convai returned an empty assistant message")
    return combined, new_conversation_id
