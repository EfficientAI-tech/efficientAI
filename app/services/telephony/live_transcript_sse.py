"""Shared SSE generator for live call transcript turns stored on CallRecording."""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator, Callable, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import CallRecording

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
    poll_interval_seconds: float = 1.0,
) -> AsyncIterator[str]:
    """Yield SSE data lines for new live_transcript entries until the call ends."""
    from app.database import SessionLocal

    seen = 0
    while True:
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
        await asyncio.sleep(poll_interval_seconds)
