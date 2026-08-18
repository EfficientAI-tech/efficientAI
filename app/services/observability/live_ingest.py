"""Helpers for incremental live observability event ingest."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Dict, Optional


class StaleLiveEventError(ValueError):
    """Raised when an event falls outside the accepted out-of-order window."""


def parse_live_event_ts(raw_value: Any) -> datetime:
    """Parse live event timestamp to a UTC-aware datetime."""
    if isinstance(raw_value, datetime):
        parsed = raw_value
    elif isinstance(raw_value, str):
        parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
    else:
        raise ValueError("event_ts must be an ISO-8601 string")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def derive_live_call_event(event_type: str) -> str:
    normalized = (event_type or "").strip().lower()
    if normalized == "call.started":
        return "call_started"
    if normalized in {"call.ended", "session.ended"}:
        return "call_ended"
    if normalized in {"call.failed", "session.failed"}:
        return "call_failed"
    if normalized.startswith("turn."):
        return "call_in_progress"
    return normalized.replace(".", "_") or "call_in_progress"


def _upsert_live_turn(turns: list[Dict[str, Any]], entry: Dict[str, Any]) -> None:
    turn_id = entry.get("turn_id")
    role = str(entry.get("role") or "").strip().lower() or "unknown"
    replace_last_by_role = bool(entry.get("replace_last_by_role"))

    if turn_id:
        for idx, item in enumerate(turns):
            if str(item.get("turn_id")) == str(turn_id):
                turns[idx] = entry
                return

    if replace_last_by_role:
        for idx in range(len(turns) - 1, -1, -1):
            if str(turns[idx].get("role") or "").strip().lower() == role:
                turns[idx] = entry
                return

    turns.append(entry)


def _sync_messages_from_live_turns(turns: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    messages: list[Dict[str, Any]] = []
    for turn in turns:
        content = turn.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        messages.append(
            {
                "role": turn.get("role") or "unknown",
                "content": content,
                "timestamp": turn.get("event_ts"),
                "start_time": turn.get("start_time"),
                "end_time": turn.get("end_time"),
            }
        )
    return messages


def merge_live_event_call_data(
    *,
    existing_call_data: Dict[str, Any],
    event: Dict[str, Any],
    max_out_of_order_seq: int,
) -> Dict[str, Any]:
    """Merge a live event into existing call_data while preserving prior keys."""
    merged = deepcopy(existing_call_data) if isinstance(existing_call_data, dict) else {}
    payload = event.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    event_type = str(event.get("event_type") or "").strip().lower()
    seq = event.get("seq")

    live_state = merged.get("live_state")
    if not isinstance(live_state, dict):
        live_state = {}
    watermark = live_state.get("max_seq")
    if isinstance(watermark, (int, float)) and isinstance(seq, (int, float)):
        if int(watermark) - int(seq) > max_out_of_order_seq:
            raise StaleLiveEventError("event sequence is older than accepted out-of-order window")

    event_ts = str(event.get("event_ts"))
    merged["_live_last_event_ts"] = event_ts
    if isinstance(seq, (int, float)):
        merged["_live_last_event_seq"] = int(seq)
        if not isinstance(watermark, (int, float)) or int(seq) > int(watermark):
            live_state["max_seq"] = int(seq)
    live_state["last_event_type"] = event_type
    live_state["last_platform"] = event.get("platform")
    merged["live_state"] = live_state

    if event_type == "call.started":
        merged["startedAt"] = payload.get("startedAt") or payload.get("started_at") or event_ts
        merged["status"] = payload.get("status") or "in_progress"
    elif event_type in {"call.ended", "call.failed", "session.ended", "session.failed"}:
        merged["endedAt"] = payload.get("endedAt") or payload.get("ended_at") or event_ts
        if payload.get("endedReason"):
            merged["endedReason"] = payload.get("endedReason")
        merged["status"] = payload.get("status") or ("failed" if "failed" in event_type else "ended")
    elif event_type.startswith("turn."):
        live_turns = merged.get("live_transcript")
        if not isinstance(live_turns, list):
            live_turns = []
        turn_entry = {
            "turn_id": payload.get("turn_id"),
            "role": payload.get("role") or event_type.split(".", 1)[1],
            "content": payload.get("content") or payload.get("text") or "",
            "event_ts": event_ts,
            "seq": seq,
            "start_time": payload.get("start_time"),
            "end_time": payload.get("end_time"),
            "replace_last_by_role": bool(payload.get("replace_last_by_role")),
        }
        if isinstance(payload.get("latency"), dict):
            turn_entry["latency"] = payload.get("latency")
        _upsert_live_turn(live_turns, turn_entry)
        merged["live_transcript"] = live_turns
        merged["messages"] = _sync_messages_from_live_turns(live_turns)
        merged["status"] = payload.get("status") or "in_progress"

    # Keep a small event ledger in payload for easier debugging.
    recent_events = merged.get("live_recent_events")
    if not isinstance(recent_events, list):
        recent_events = []
    recent_events.append(
        {
            "event_id": event.get("event_id"),
            "event_type": event_type,
            "seq": seq,
            "event_ts": event_ts,
        }
    )
    merged["live_recent_events"] = recent_events[-30:]
    return merged
