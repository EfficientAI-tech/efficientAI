"""Text chat over Smallest Atoms realtime WebSocket (mode=chat, input_text.send)."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import websockets.sync.client
from loguru import logger
from websockets.exceptions import ConnectionClosed, ConnectionClosedOK

from app.services.agents.smallest_atoms_connect import chat_websocket_uri, parse_inbound_event
from app.services.agents.smallest_atoms_protocol import (
    USER_MESSAGE_OUTBOUND_TYPE,
    apply_session_meta,
    event_type,
    is_write_conflict_message,
    parse_error_message,
)


@dataclass(frozen=True)
class AtomsChatTimeouts:
    turn_seconds: float = 90.0
    connect_open_seconds: float = 30.0
    recv_slice_seconds: float = 5.0
    settle_quiet_seconds: float = 2.5
    greeting_wait_seconds: float = 1.5


def _looks_like_filler(text: str) -> bool:
    t = (text or "").strip()
    return t.endswith("…") or t.endswith("...")


@dataclass
class _TurnCollector:
    parts: list[str] = field(default_factory=list)
    done: threading.Event = field(default_factory=threading.Event)
    quiet_timer: Optional[threading.Timer] = None
    error: Optional[BaseException] = None

    def combined(self) -> str:
        return "\n".join(self.parts).strip()


class SmallestAtomsChatSession:
    """One mode=chat WebSocket per eval simulation (multi-turn)."""

    def __init__(
        self,
        api_key: str,
        agent_id: str,
        *,
        timeout: float = 90.0,
        timeouts: Optional[AtomsChatTimeouts] = None,
        on_inbound_event: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> None:
        self._api_key = api_key
        self._agent_id = agent_id
        self._timeouts = timeouts or AtomsChatTimeouts(turn_seconds=timeout)
        self._on_inbound_event = on_inbound_event
        self._ws: Any = None
        self._session_ready = False
        self._active_turn: Optional[_TurnCollector] = None
        self._lock = threading.Lock()
        self.meta: dict[str, Any] = {}

    def close(self) -> None:
        ws = self._ws
        self._ws = None
        self._session_ready = False
        if ws is None:
            return
        try:
            ws.send(json.dumps({"type": "session.close"}))
        except Exception:
            pass
        try:
            ws.close()
        except Exception:
            pass

    def _connect_and_wait_session(self) -> None:
        if self._ws is not None and self._session_ready:
            return
        t = self._timeouts
        uri = chat_websocket_uri(self._api_key, self._agent_id)
        self._ws = websockets.sync.client.connect(
            uri,
            open_timeout=min(t.connect_open_seconds, t.turn_seconds),
            close_timeout=5,
            ping_interval=20,
            ping_timeout=min(60.0, t.turn_seconds),
        )
        deadline = time.monotonic() + min(t.connect_open_seconds, t.turn_seconds)
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            try:
                raw = self._ws.recv(timeout=min(t.recv_slice_seconds, remaining))
            except TimeoutError:
                continue
            event = parse_inbound_event(raw)
            if not event:
                continue
            if self._on_inbound_event:
                self._on_inbound_event(event)
            et = event_type(event)
            if et == "error":
                raise ValueError(parse_error_message(event))
            apply_session_meta(event, self.meta)
            if et == "session.created":
                self._session_ready = True
                if t.greeting_wait_seconds > 0:
                    self._drain_greeting(t.greeting_wait_seconds)
                return
            if et == "session.closed":
                raise ValueError(
                    f"Smallest chat closed before session.created ({event.get('reason') or 'ended'})"
                )
        raise ValueError("Timed out waiting for Smallest session.created on chat WebSocket")

    def _drain_greeting(self, wait_seconds: float) -> None:
        deadline = time.monotonic() + wait_seconds
        t = self._timeouts
        while time.monotonic() < deadline and self._ws is not None:
            remaining = deadline - time.monotonic()
            try:
                raw = self._ws.recv(timeout=min(t.recv_slice_seconds, remaining))
            except TimeoutError:
                return
            event = parse_inbound_event(raw)
            if event and self._on_inbound_event:
                self._on_inbound_event(event)
            if event:
                apply_session_meta(event, self.meta)

    def _cancel_quiet_timer(self, turn: _TurnCollector) -> None:
        if turn.quiet_timer:
            turn.quiet_timer.cancel()
            turn.quiet_timer = None

    def _arm_settle_timer(self, turn: _TurnCollector, wait_seconds: float) -> None:
        self._cancel_quiet_timer(turn)

        def settle() -> None:
            with self._lock:
                if self._active_turn is turn:
                    self._active_turn = None
                turn.done.set()

        turn.quiet_timer = threading.Timer(wait_seconds, settle)
        turn.quiet_timer.daemon = True
        turn.quiet_timer.start()

    def _handle_inbound(self, event: dict[str, Any]) -> None:
        if self._on_inbound_event:
            self._on_inbound_event(event)
        et = event_type(event)
        if et == "error":
            msg = parse_error_message(event)
            if is_write_conflict_message(msg):
                raise ValueError(
                    "Smallest Atoms returned Write Conflict (session busy or overlapping connection). "
                    "Retry the eval; avoid running many Smallest chat evals on the same agent at once."
                )
            raise ValueError(msg)
        apply_session_meta(event, self.meta)

        if et != "transcript":
            if et == "session.closed" and self._active_turn:
                turn = self._active_turn
                self._cancel_quiet_timer(turn)
                if turn.parts:
                    with self._lock:
                        if self._active_turn is turn:
                            self._active_turn = None
                    turn.done.set()
            return

        role = str(event.get("role") or event.get("speaker") or "").lower()
        if role == "user":
            return
        text = event.get("text") or event.get("transcript")
        if not isinstance(text, str) or not text.strip():
            return
        turn = self._active_turn
        if turn is None:
            return
        turn.parts.append(text.strip())
        t = self._timeouts
        tool_wait = min(max(t.turn_seconds - 2.0, t.settle_quiet_seconds), 15.0)
        wait = tool_wait if _looks_like_filler(text) else t.settle_quiet_seconds
        self._arm_settle_timer(turn, wait)

    def _recv_until_turn_done(self, turn: _TurnCollector) -> str:
        t = self._timeouts
        deadline = time.monotonic() + t.turn_seconds
        while time.monotonic() < deadline and self._ws is not None:
            if turn.done.wait(timeout=min(t.recv_slice_seconds, deadline - time.monotonic())):
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                raw = self._ws.recv(timeout=min(t.recv_slice_seconds, remaining))
            except TimeoutError:
                continue
            except (ConnectionClosedOK, ConnectionClosed) as exc:
                self._ws = None
                self._session_ready = False
                if turn.parts:
                    return turn.combined()
                raise ValueError(f"Smallest chat connection closed ({exc})") from exc
            event = parse_inbound_event(raw)
            if event:
                self._handle_inbound(event)

        self._cancel_quiet_timer(turn)
        with self._lock:
            if self._active_turn is turn:
                self._active_turn = None
        combined = turn.combined()
        if combined:
            return combined
        if turn.error:
            raise turn.error
        raise ValueError(
            "Smallest chat returned an empty assistant message "
            f"(timed out after {t.turn_seconds}s waiting for a reply)"
        )

    def send_user_message(self, user_text: str) -> str:
        user_text = (user_text or "").strip()
        if not user_text:
            raise ValueError("Smallest chat requires a non-empty user message")

        for attempt in range(2):
            try:
                self._connect_and_wait_session()
                if self._ws is None:
                    raise ValueError("Smallest chat WebSocket is not connected")

                turn = _TurnCollector()
                with self._lock:
                    self._active_turn = turn
                payload = json.dumps({"type": USER_MESSAGE_OUTBOUND_TYPE, "text": user_text})
                self._ws.send(payload)
                return self._recv_until_turn_done(turn)
            except ValueError as exc:
                if attempt == 0 and is_write_conflict_message(str(exc)):
                    self.close()
                    time.sleep(0.5)
                    continue
                raise
            except Exception as exc:
                self.close()
                if attempt == 0:
                    time.sleep(0.35)
                    continue
                raise ValueError(f"Smallest chat WebSocket failed: {exc}") from exc
        raise ValueError("Smallest chat failed after retry")


def smallest_atoms_chat_reply(
    api_key: str,
    agent_id: str,
    user_text: str,
    *,
    timeout: float = 90.0,
    session: Optional[SmallestAtomsChatSession] = None,
) -> tuple[str, dict[str, Any]]:
    if session is not None:
        text = session.send_user_message(user_text)
        return text, dict(session.meta)

    one_shot = SmallestAtomsChatSession(api_key, agent_id, timeout=timeout)
    try:
        text = one_shot.send_user_message(user_text)
        return text, dict(one_shot.meta)
    finally:
        one_shot.close()
