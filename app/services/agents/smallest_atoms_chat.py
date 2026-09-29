"""Text chat over Smallest Atoms LiveKit data channel (mode=chat / atoms-client-sdk)."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from loguru import logger

from app.services.agents.smallest_atoms_connect import (
    SmallestChatCredentials,
    parse_inbound_event,
    resolve_chat_credentials,
)
from app.services.agents.smallest_atoms_protocol import (
    SmallestAtomsTurnAccumulator,
    apply_session_meta,
    is_write_conflict_message,
)


@dataclass(frozen=True)
class AtomsChatTimeouts:
    turn_seconds: float = 90.0
    connect_open_seconds: float = 30.0


def _user_data_payload(user_text: str) -> bytes:
    return json.dumps(
        {
            "type": "transcript",
            "text": user_text,
            "topic": "user_response",
            "timestamp": int(time.time() * 1000),
        }
    ).encode("utf-8")


class SmallestAtomsChatSession:
    """One LiveKit room per eval simulation (multi-turn), mirroring atoms-client-sdk chat mode."""

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
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever,
            name="smallest-atoms-chat",
            daemon=True,
        )
        self._thread.start()
        self._room: Any = None
        self._creds: SmallestChatCredentials | None = None
        self._pending_acc: SmallestAtomsTurnAccumulator | None = None
        self._turn_done: asyncio.Event | None = None
        self._turn_error: BaseException | None = None
        self.meta: dict[str, Any] = {}

    def close(self) -> None:
        try:
            self._submit(self._disconnect_async(), timeout=15.0)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=3.0)

    def _submit(self, coro: Any, *, timeout: float) -> Any:
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    def _on_livekit_data(self, data: bytes) -> None:
        event = parse_inbound_event(data)
        if not event:
            return
        if self._on_inbound_event:
            self._on_inbound_event(event)
        acc = self._pending_acc
        if acc is None:
            apply_session_meta(event, self.meta)
            return
        try:
            if self._feed_turn_event(acc, event) and self._turn_done:
                self._turn_done.set()
        except ValueError as exc:
            self._turn_error = exc
            if self._turn_done:
                self._turn_done.set()

    def _feed_turn_event(self, acc: SmallestAtomsTurnAccumulator, event: dict[str, Any]) -> bool:
        result = acc.feed(event)
        if result.error_message:
            if is_write_conflict_message(result.error_message):
                raise ValueError(
                    "Smallest Atoms returned Write Conflict (session busy or overlapping connection). "
                    "Retry the eval; avoid running many Smallest chat evals on the same agent at once."
                )
            raise ValueError(result.error_message)
        return result.turn_complete

    async def _connect_async(self) -> None:
        if self._room is not None:
            return
        try:
            from livekit import rtc
            from livekit.rtc import Room, RoomOptions
        except ImportError as exc:
            raise ValueError(
                "Smallest chat requires the livekit package (pip install livekit)"
            ) from exc

        self._creds = resolve_chat_credentials(self._api_key, self._agent_id)
        if self._creds.conversation_id:
            self.meta.setdefault("smallest_call_id", self._creds.conversation_id)

        room = Room()
        self._room = room

        @room.on("data_received")
        def on_data_received(data_packet: Any) -> None:
            try:
                payload = bytes(data_packet.data)
            except Exception:
                return
            self._on_livekit_data(payload)

        open_timeout = min(self._timeouts.connect_open_seconds, self._timeouts.turn_seconds)
        await asyncio.wait_for(
            room.connect(
                self._creds.host,
                self._creds.access_token,
                options=RoomOptions(auto_subscribe=False),
            ),
            timeout=open_timeout,
        )
        logger.debug(
            "Smallest chat LiveKit connected (room={}, host={})",
            getattr(room, "name", None),
            self._creds.host,
        )

    async def _disconnect_async(self) -> None:
        room = self._room
        self._room = None
        self._creds = None
        self._pending_acc = None
        self._turn_done = None
        if room is None:
            return
        try:
            await room.disconnect()
        except Exception:
            pass

    async def _send_turn_async(self, user_text: str) -> str:
        await self._connect_async()
        if self._room is None:
            raise ValueError("Smallest chat LiveKit room is not connected")

        acc = SmallestAtomsTurnAccumulator(meta=dict(self.meta))
        self._pending_acc = acc
        self._turn_done = asyncio.Event()

        await self._room.local_participant.publish_data(
            _user_data_payload(user_text),
            reliable=True,
        )

        try:
            await asyncio.wait_for(self._turn_done.wait(), timeout=self._timeouts.turn_seconds)
        except asyncio.TimeoutError:
            pass
        finally:
            self._pending_acc = None
            self._turn_done = None

        if self._turn_error is not None:
            err = self._turn_error
            self._turn_error = None
            raise err

        self.meta.update(acc.meta)
        combined = acc.combined_reply()
        if not combined:
            raise ValueError(
                "Smallest chat returned an empty assistant message "
                f"(timed out after {self._timeouts.turn_seconds}s waiting for a reply; "
                f"inbound types seen: {acc.seen_event_types[-16:]})"
            )
        return combined

    def send_user_message(self, user_text: str) -> str:
        user_text = (user_text or "").strip()
        if not user_text:
            raise ValueError("Smallest chat requires a non-empty user message")

        for attempt in range(2):
            try:
                return self._submit(
                    self._send_turn_async(user_text),
                    timeout=self._timeouts.turn_seconds + 30.0,
                )
            except ValueError as exc:
                if attempt == 0 and is_write_conflict_message(str(exc)):
                    self._submit(self._disconnect_async(), timeout=15.0)
                    time.sleep(0.5)
                    continue
                raise
            except Exception as exc:
                self._submit(self._disconnect_async(), timeout=15.0)
                if attempt == 0:
                    time.sleep(0.35)
                    continue
                raise ValueError(f"Smallest chat LiveKit failed: {exc}") from exc
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
