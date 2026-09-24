"""Text chat over Smallest Atoms realtime WebSocket (mode=chat)."""

from __future__ import annotations

import json
from typing import Any, Optional
from urllib.parse import quote

import websockets.sync.client


def smallest_atoms_chat_reply(
    api_key: str,
    agent_id: str,
    user_text: str,
    *,
    timeout: float = 90.0,
) -> tuple[str, dict[str, Any]]:
    token = quote(api_key.strip(), safe="")
    uri = (
        f"wss://api.smallest.ai/atoms/v1/agent/connect"
        f"?agent_id={quote(agent_id.strip(), safe='')}&mode=chat&token={token}"
    )

    reply_parts: list[str] = []
    meta: dict[str, Any] = {}

    with websockets.sync.client.connect(uri, open_timeout=timeout, close_timeout=5) as ws:
        user_sent = False
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
            if etype == "error":
                raise ValueError(event.get("message") or event.get("error") or str(event))

            if etype in ("session.created", "session.started"):
                cid = event.get("call_id") or event.get("conversation_id") or event.get("session_id")
                if cid:
                    meta["smallest_call_id"] = cid

            if not user_sent and user_text.strip():
                ws.send(json.dumps({"type": "input_text.send", "text": user_text.strip()}))
                user_sent = True
                continue

            if etype == "transcript":
                role = str(event.get("role") or event.get("speaker") or "").lower()
                text = event.get("text") or event.get("transcript")
                if role in ("assistant", "agent", "ai") and isinstance(text, str) and text.strip():
                    reply_parts.append(text.strip())
            elif etype in ("agent_stop_talking", "session.closed"):
                if reply_parts or etype == "session.closed":
                    break

    combined = " ".join(reply_parts).strip()
    if not combined:
        raise ValueError("Smallest chat returned an empty assistant message")
    return combined, meta
