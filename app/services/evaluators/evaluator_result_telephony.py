"""Helpers for linking evaluator results to live telephony call recordings."""

from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import CallRecording, CallRecordingSource, EvaluatorResult
from app.services.telephony.live_transcript_sse import is_live_call_event


def find_evaluator_telephony_recording(
    db: Session,
    result: EvaluatorResult,
) -> Optional[CallRecording]:
    """Return the webhook call recording linked to an evaluator result (not playground)."""
    recording = (
        db.query(CallRecording)
        .filter(
            CallRecording.evaluator_result_id == result.id,
            CallRecording.source == CallRecordingSource.WEBHOOK,
        )
        .first()
    )
    if recording:
        from app.services.live_entity_storage import hydrate_call_recordings

        hydrate_call_recordings([recording])
    return recording


def enrich_evaluator_result_live_telephony(
    db: Session,
    result: EvaluatorResult,
    call_data: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Merge live telephony fields from the linked CallRecording into call_data."""
    merged: Dict[str, Any] = dict(call_data) if isinstance(call_data, dict) else {}
    recording = find_evaluator_telephony_recording(db, result)
    if not recording:
        return merged

    rec_data = recording.call_data if isinstance(recording.call_data, dict) else {}
    live_transcript = rec_data.get("live_transcript") or []
    merged.setdefault("call_short_id", recording.call_short_id)
    if recording.call_event:
        merged["call_event"] = recording.call_event
    if is_live_call_event(recording.call_event):
        merged["is_live"] = True
        merged["live_transcript"] = live_transcript if isinstance(live_transcript, list) else []
    elif live_transcript:
        merged["live_transcript"] = live_transcript
    return merged
