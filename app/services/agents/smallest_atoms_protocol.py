"""Smallest Atoms chat WebSocket (mode=chat) — inbound event protocol.

Pure parsing and turn accumulation. Transport lives in smallest_atoms_chat.py.
Extend SESSION_META_TYPES / TURN_COMPLETE_TYPES when probe or fixtures show new shapes.
Golden transcripts: tests/fixtures/smallest_atoms_chat/
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Optional

USER_MESSAGE_OUTBOUND_TYPE = "input_text.send"

SESSION_META_TYPES = frozenset(
    {
        "session.created",
        "session.started",
        "session_created",
        "session_started",
        "conversation.started",
        "conversation_started",
    }
)

TURN_COMPLETE_TYPES = frozenset(
    {
        "agent_stop_talking",
        "session.closed",
        "session.ended",
        "conversation.ended",
        "turn.completed",
        "response.completed",
        "response.done",
    }
)

ASSISTANT_ROLES = frozenset({"assistant", "agent", "ai"})
USER_ROLES = frozenset({"user", "human", "caller"})


class InboundKind(str, Enum):
    SESSION_META = "session_meta"
    ASSISTANT_TEXT = "assistant_text"
    TURN_COMPLETE = "turn_complete"
    ERROR = "error"
    NOOP = "noop"
    UNKNOWN = "unknown"


def is_write_conflict_message(message: str) -> bool:
    return "write conflict" in (message or "").lower()


def event_type(event: dict[str, Any]) -> str:
    return str(event.get("type") or "")


def parse_error_message(event: dict[str, Any]) -> str:
    return str(event.get("message") or event.get("error") or event)


def apply_session_meta(event: dict[str, Any], meta: dict[str, Any]) -> None:
    if event_type(event) not in SESSION_META_TYPES:
        return
    cid = event.get("call_id") or event.get("conversation_id") or event.get("session_id")
    if cid:
        meta["smallest_call_id"] = cid


def extract_assistant_text(event: dict[str, Any]) -> Optional[str]:
    etype = event_type(event)
    if etype == "transcript":
        topic = str(event.get("topic") or "").lower()
        role = str(event.get("role") or event.get("speaker") or "").lower()
        text = event.get("text") or event.get("transcript")
        if topic == "user_response" or role in USER_ROLES:
            return None
        if isinstance(text, str) and text.strip():
            return text.strip()
        return None
    if etype in ("agent_response", "message", "response"):
        role = str(event.get("role") or event.get("speaker") or "assistant").lower()
        if role in USER_ROLES:
            return None
        text = event.get("text") or event.get("content") or event.get("message")
        if isinstance(text, str) and text.strip():
            return text.strip()
    update = event.get("update")
    if isinstance(update, dict):
        nested = extract_assistant_text({**update, "type": update.get("type") or "transcript"})
        if nested:
            return nested
    return None


def classify_inbound_event(event: dict[str, Any]) -> InboundKind:
    etype = event_type(event)
    if etype == "error":
        return InboundKind.ERROR
    if etype in SESSION_META_TYPES:
        return InboundKind.SESSION_META
    if etype in TURN_COMPLETE_TYPES:
        return InboundKind.TURN_COMPLETE
    if extract_assistant_text(event):
        return InboundKind.ASSISTANT_TEXT
    if etype in ("ping", "pong", "heartbeat", "keepalive"):
        return InboundKind.NOOP
    if not etype:
        return InboundKind.UNKNOWN
    return InboundKind.UNKNOWN


@dataclass
class TurnFeedResult:
    turn_complete: bool = False
    assistant_chunk: Optional[str] = None
    kind: InboundKind = InboundKind.NOOP
    error_message: Optional[str] = None


@dataclass
class SmallestAtomsTurnAccumulator:
    """Stateful turn parser for tests and live sessions."""

    reply_parts: list[str] = field(default_factory=list)
    seen_event_types: list[str] = field(default_factory=list)
    unknown_event_types: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def combined_reply(self) -> str:
        return " ".join(self.reply_parts).strip()

    def feed(self, event: dict[str, Any]) -> TurnFeedResult:
        etype = event_type(event)
        if etype:
            self.seen_event_types.append(etype)

        kind = classify_inbound_event(event)
        apply_session_meta(event, self.meta)

        if kind == InboundKind.ERROR:
            msg = parse_error_message(event)
            return TurnFeedResult(kind=kind, error_message=msg)

        chunk = extract_assistant_text(event)
        if chunk:
            self.reply_parts.append(chunk)

        if kind == InboundKind.UNKNOWN and etype:
            self.unknown_event_types.append(etype)

        if kind == InboundKind.TURN_COMPLETE:
            complete = bool(self.reply_parts) or etype in ("session.closed", "session.ended")
            return TurnFeedResult(
                kind=kind,
                turn_complete=complete,
                assistant_chunk=chunk,
            )

        return TurnFeedResult(kind=kind, assistant_chunk=chunk)


def replay_events_until_turn_complete(events: Iterable[dict[str, Any]]) -> SmallestAtomsTurnAccumulator:
    acc = SmallestAtomsTurnAccumulator()
    for event in events:
        result = acc.feed(event)
        if result.error_message:
            if is_write_conflict_message(result.error_message):
                raise ValueError(
                    "Smallest Atoms returned Write Conflict (session busy or overlapping connection). "
                    "Retry the eval; avoid running many Smallest chat evals on the same agent at once."
                )
            raise ValueError(result.error_message)
        if result.turn_complete:
            break
    return acc


def load_fixture_events(path: Path) -> list[dict[str, Any]]:
    raw = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        events: list[dict[str, Any]] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            events.append(json.loads(line))
        return events
    data = json.loads(raw)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "events" in data:
        return list(data["events"])
    raise ValueError(f"Unsupported fixture format: {path}")
