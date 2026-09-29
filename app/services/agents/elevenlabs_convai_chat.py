"""Synchronous text turns against ElevenLabs ConvAI WebSocket."""

from __future__ import annotations

import json
import time
from typing import Any, Optional

import websockets.sync.client
from websockets.exceptions import ConnectionClosed, ConnectionClosedOK


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


def _collapse_obvious_duplicate(text: str) -> str:
    """Some ConvAI text streams deliver the same line twice (spaced + clean)."""
    stripped = (text or "").strip()
    if not stripped:
        return stripped

    def _norm(value: str) -> str:
        return "".join(value.split())

    words = stripped.split()
    if len(words) >= 4 and len(words) % 2 == 0:
        mid = len(words) // 2
        if words[:mid] == words[mid:]:
            return " ".join(words[:mid])

    if len(stripped) >= 16:
        half = len(stripped) // 2
        left, right = stripped[:half].strip(), stripped[half:].strip()
        if left and right and _norm(left) == _norm(right):
            return left
    return stripped


def _parse_event(raw: Any) -> Optional[dict[str, Any]]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return event if isinstance(event, dict) else None


class ElevenLabsConvaiSession:
    """One WebSocket for an entire eval simulation (multi-turn)."""

    def __init__(self, api_key: str, agent_id: str, *, timeout: float = 90.0) -> None:
        self._api_key = api_key
        self._agent_id = agent_id
        self._timeout = timeout
        self._ws: Any = None
        self.conversation_id: Optional[str] = None
        self._init_complete = False

    def close(self) -> None:
        ws = self._ws
        self._ws = None
        self._init_complete = False
        if ws is None:
            return
        try:
            ws.close()
        except Exception:
            pass

    def _connect(self) -> None:
        if self._ws is not None:
            return
        query = f"agent_id={self._agent_id}"
        if self.conversation_id:
            query += f"&conversation_id={self.conversation_id}"
        uri = f"wss://api.elevenlabs.io/v1/convai/conversation?{query}"
        self._ws = websockets.sync.client.connect(
            uri,
            additional_headers={"xi-api-key": self._api_key},
            open_timeout=self._timeout,
            close_timeout=5,
            ping_interval=20,
            ping_timeout=self._timeout,
        )
        if not self.conversation_id:
            init = {
                "type": "conversation_initiation_client_data",
                "conversation_config_override": {
                    "conversation": {"text_only": True},
                },
            }
            self._ws.send(json.dumps(init))
        self._init_complete = bool(self.conversation_id)
        self._drain_until_ready()

    def _recv_event(self, *, timeout: Optional[float] = None) -> Optional[dict[str, Any]]:
        if self._ws is None:
            return None
        raw = self._ws.recv(timeout=timeout if timeout is not None else self._timeout)
        return _parse_event(raw)

    def _process_inbound_event(self, event: dict[str, Any]) -> Optional[str]:
        etype = str(event.get("type") or "")
        if etype == "ping":
            _handle_ping(self._ws, event)
            return None
        if etype == "conversation_initiation_metadata":
            meta = event.get("conversation_initiation_metadata_event") or event.get(
                "conversation_initiation_metadata"
            )
            if isinstance(meta, dict):
                cid = meta.get("conversation_id")
                if isinstance(cid, str) and cid.strip():
                    self.conversation_id = cid.strip()
            return None
        if etype == "error":
            msg = event.get("message") or event.get("error")
            raise ValueError(f"ElevenLabs convai error: {msg or event}")
        return _extract_agent_text_from_event(event)

    def _drain_until_ready(self) -> None:
        while not self._init_complete and self._ws is not None:
            event = self._recv_event()
            if not event:
                continue
            etype = str(event.get("type") or "")
            if etype == "ping":
                _handle_ping(self._ws, event)
                continue
            if etype == "conversation_initiation_metadata":
                meta = event.get("conversation_initiation_metadata_event") or event.get(
                    "conversation_initiation_metadata"
                )
                if isinstance(meta, dict):
                    cid = meta.get("conversation_id")
                    if isinstance(cid, str) and cid.strip():
                        self.conversation_id = cid.strip()
                self._init_complete = True
                self._flush_proactive_agent_greeting()
                return
            if etype == "error":
                msg = event.get("message") or event.get("error")
                raise ValueError(f"ElevenLabs convai error: {msg or event}")

    def _flush_proactive_agent_greeting(self) -> None:
        """Drop the agent's unsolicited opening line before the first user turn."""
        deadline = time.monotonic() + 2.5
        while time.monotonic() < deadline and self._ws is not None:
            try:
                event = self._recv_event(timeout=0.35)
            except TimeoutError:
                break
            if not event:
                continue
            etype = str(event.get("type") or "")
            self._process_inbound_event(event)
            if etype in (
                "agent_response",
                "agent_response_end",
                "agent_chat_response_part_end",
            ):
                return

    def _collect_reply(self) -> str:
        delta_parts: list[str] = []
        final_text: Optional[str] = None
        while self._ws is not None:
            try:
                event = self._recv_event()
            except (ConnectionClosedOK, ConnectionClosed) as exc:
                self._ws = None
                self._init_complete = False
                raise ValueError(
                    f"ElevenLabs convai connection closed before a full reply ({exc})"
                ) from exc
            if not event:
                continue
            etype = str(event.get("type") or "")
            chunk = self._process_inbound_event(event)
            if chunk:
                if etype in ("agent_response", "agent_response_event"):
                    final_text = chunk
                    delta_parts.clear()
                elif etype == "agent_response_correction":
                    final_text = chunk
                    delta_parts.clear()
                elif etype == "agent_chat_response_part" and final_text is None:
                    delta_parts.append(chunk)

            if etype in (
                "agent_response",
                "agent_response_end",
                "agent_chat_response_part_end",
            ):
                if final_text or delta_parts:
                    break

        if final_text:
            return _collapse_obvious_duplicate(final_text)
        combined = "".join(delta_parts).strip() or " ".join(delta_parts).strip()
        combined = _collapse_obvious_duplicate(combined)
        if not combined:
            raise ValueError("ElevenLabs convai returned an empty assistant message")
        return combined

    def send_user_message(self, user_text: str) -> str:
        user_text = (user_text or "").strip()
        if not user_text:
            raise ValueError("ElevenLabs convai requires a non-empty user message")

        for attempt in range(2):
            try:
                self._connect()
                self._ws.send(json.dumps({"type": "user_message", "text": user_text}))
                return self._collect_reply()
            except (ConnectionClosedOK, ConnectionClosed, ValueError) as exc:
                self.close()
                if attempt == 0 and self.conversation_id:
                    continue
                if isinstance(exc, ValueError) and "connection closed" not in str(exc).lower():
                    raise
                raise ValueError(
                    f"ElevenLabs convai WebSocket closed during simulation ({exc}). "
                    "Retry the eval; if it persists, check ElevenLabs agent limits and API status."
                ) from exc
        raise ValueError("ElevenLabs convai failed after reconnect")


def elevenlabs_convai_reply(
    api_key: str,
    agent_id: str,
    user_text: str,
    *,
    conversation_id: Optional[str] = None,
    timeout: float = 90.0,
    session: Optional[ElevenLabsConvaiSession] = None,
) -> tuple[str, Optional[str]]:
    if session is not None:
        if conversation_id and not session.conversation_id:
            session.conversation_id = conversation_id
        text = session.send_user_message(user_text)
        return text, session.conversation_id

    one_shot = ElevenLabsConvaiSession(api_key, agent_id, timeout=timeout)
    if conversation_id:
        one_shot.conversation_id = conversation_id
    try:
        text = one_shot.send_user_message(user_text)
        return text, one_shot.conversation_id
    finally:
        one_shot.close()
