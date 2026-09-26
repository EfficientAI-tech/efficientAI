"""Shared SSE generator for live call transcript turns stored on CallRecording."""

from __future__ import annotations

import asyncio
import json
import time
from typing import AsyncIterator, Callable, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import CallRecording
from app.services.telephony.live_transcript import _channel, _get_redis

LIVE_CALL_EVENTS = frozenset(
    {
        "outbound_initiated",
        "ringing",
        "call_started",
        "call_in_progress",
        "in-progress",
        "answered",
    }
)


def is_live_call_event(call_event: Optional[str]) -> bool:
    return (call_event or "") in LIVE_CALL_EVENTS


async def stream_live_transcript_events(
    *,
    call_short_id: str,
    bound_recording_id: UUID,
    fetch_recording: Callable[[Session], Optional[CallRecording]],
    poll_interval_seconds: float = 5.0,
) -> AsyncIterator[str]:
    """Yield SSE data lines for new live_transcript entries until the call ends."""
    from app.database import SessionLocal

    seen = 0
    session = SessionLocal()
    try:
        row = fetch_recording(session)
        if not row:
            return
        data = row.call_data if isinstance(row.call_data, dict) else {}
        transcript = data.get("live_transcript") or []
        if len(transcript) > seen:
            for entry in transcript[seen:]:
                yield f"data: {json.dumps(entry)}\n\n"
            seen = len(transcript)
        if not is_live_call_event(row.call_event):
            return
    finally:
        session.close()

    pubsub = _get_redis().pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(_channel(call_short_id))
    last_reconcile = time.monotonic()

    try:
        while True:
            message = await asyncio.to_thread(pubsub.get_message, timeout=1.0)
            if message and message.get("type") == "message":
                data = message.get("data")
                if data:
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        event = None
                    if event:
                        if event.get("type") == "transcript":
                            yield f"data: {json.dumps(event)}\n\n"
                        elif event.get("type") == "call_event":
                            if not is_live_call_event(event.get("call_event")):
                                break

            if time.monotonic() - last_reconcile < poll_interval_seconds:
                continue
            last_reconcile = time.monotonic()

            session = SessionLocal()
            try:
                row = fetch_recording(session)
                if not row:
                    break
                data = row.call_data if isinstance(row.call_data, dict) else {}
                transcript = data.get("live_transcript") or []
                if len(transcript) > seen:
                    for entry in transcript[seen:]:
                        yield f"data: {json.dumps(entry)}\n\n"
                    seen = len(transcript)
                if not is_live_call_event(row.call_event):
                    break
            finally:
                session.close()
    finally:
        try:
            pubsub.unsubscribe(_channel(call_short_id))
            pubsub.close()
        except Exception:
            pass
