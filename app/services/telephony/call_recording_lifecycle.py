"""Helpers for Vobiz / live call CallRecording lifecycle updates."""

from __future__ import annotations

import random
import string
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.database import Agent, CallRecording, CallRecordingSource, EvaluatorResult
from app.models.enums import CallRecordingStatus

TERMINAL_VOBIZ_STATUSES = {
    "completed",
    "hangup",
    "failed",
    "busy",
    "no-answer",
    "canceled",
    "cancelled",
}

LIVE_CALL_EVENTS = {
    "outbound_initiated",
    "ringing",
    "call_started",
    "call_in_progress",
    "in-progress",
    "answered",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _copy_call_data(row: CallRecording) -> Dict[str, Any]:
    return dict(row.call_data) if isinstance(row.call_data, dict) else {}


def _fresh_call_data(db: Session, row: CallRecording) -> Dict[str, Any]:
    """Reload call_data from the database before mutating a long-lived session row."""
    db.expire(row, ["call_data"])
    db.refresh(row, attribute_names=["call_data"])
    return _copy_call_data(row)


def _save_call_data(db: Session, row: CallRecording, data: Dict[str, Any]) -> None:
    row.call_data = data
    flag_modified(row, "call_data")
    from app.services.live_entity_storage import sync_call_recording

    sync_call_recording(db, row)
    db.commit()
    db.refresh(row)


def _timestamp_to_ms(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value * 1000) if value < 10_000_000_000 else int(value)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return int(parsed.timestamp() * 1000)
        except ValueError:
            return None
    return None


def is_bootstrap_user_message(content: str) -> bool:
    lowered = content.strip().lower()
    return (
        lowered.startswith("start by greeting")
        or "introducing yourself based on the system instruction" in lowered
    )


def filter_conversation_turns(turns: Optional[list]) -> list:
    if not turns:
        return []
    filtered = []
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        speaker = (turn.get("speaker") or turn.get("role") or "").lower()
        text = (turn.get("text") or turn.get("content") or "").strip()
        if not text:
            continue
        if speaker in {"user", "caller"} and is_bootstrap_user_message(text):
            continue
        filtered.append(turn)
    return filtered


def _count_user_messages(messages: list) -> int:
    return sum(1 for msg in messages if isinstance(msg, dict) and msg.get("role") == "user")


def resolve_telephony_messages(
    *,
    live_transcript: list,
    conversation_turns: Optional[list] = None,
) -> list:
    """Pick the best turn-based message list for observability UI."""
    live_messages = live_transcript_to_messages(live_transcript)
    conv_messages = conversation_turns_to_messages(filter_conversation_turns(conversation_turns))

    live_user_count = _count_user_messages(live_messages)
    conv_user_count = _count_user_messages(conv_messages)

    if live_user_count >= conv_user_count and live_messages:
        return live_messages
    if conv_messages:
        return conv_messages
    return live_messages


def live_transcript_to_messages(transcript: list) -> list:
    messages = []
    for entry in transcript:
        if not isinstance(entry, dict):
            continue
        content = (entry.get("content") or "").strip()
        if not content:
            continue
        raw_role = str(entry.get("role") or "assistant").lower()
        if raw_role in {"user", "caller"}:
            role = "user"
        elif raw_role in {"agent", "assistant", "bot"}:
            role = "assistant"
        else:
            role = "assistant"
        message = {"role": role, "content": content}
        start_time = _timestamp_to_ms(entry.get("timestamp"))
        if start_time is not None:
            message["start_time"] = start_time
        messages.append(message)
    return messages


def conversation_turns_to_messages(conversation_turns: list) -> list:
    messages = []
    for turn in conversation_turns:
        if not isinstance(turn, dict):
            continue
        text = (turn.get("text") or turn.get("content") or "").strip()
        if not text:
            continue
        speaker = (turn.get("speaker") or turn.get("role") or "assistant").lower()
        role = "user" if speaker in {"user", "caller"} else "assistant"
        message = {"role": role, "content": text}
        start = turn.get("start")
        if isinstance(start, (int, float)):
            message["start_time"] = int(start * 1000)
        messages.append(message)
    return messages


def _normalize_call_event(status: Optional[str]) -> str:
    if not status:
        return "updated"
    normalized = status.lower().replace("_", "-")
    if normalized in TERMINAL_VOBIZ_STATUSES:
        if normalized in {"completed", "hangup"}:
            return "call_ended"
        if normalized in {"busy", "no-answer", "canceled", "cancelled"}:
            return "call_ended"
        return "failed"
    if normalized in {"ringing", "in-progress", "answered", "answer"}:
        return "call_in_progress"
    if normalized in {"initiated", "queued", "outbound-initiated", "outbound_initiated"}:
        return "outbound_initiated"
    return normalized


def _find_by_call_ref(db: Session, call_ref: str) -> Optional[CallRecording]:
    rows = (
        db.query(CallRecording)
        .filter(CallRecording.provider_platform == "vobiz")
        .order_by(CallRecording.created_at.desc())
        .limit(200)
        .all()
    )
    for row in rows:
        data = row.call_data if isinstance(row.call_data, dict) else {}
        if data.get("call_ref") == call_ref:
            return row
    return None


def find_call_recording(
    db: Session,
    *,
    call_ref: Optional[str] = None,
    provider_call_id: Optional[str] = None,
) -> Optional[CallRecording]:
    if provider_call_id:
        row = (
            db.query(CallRecording)
            .filter(CallRecording.provider_call_id == provider_call_id)
            .first()
        )
        if row:
            return row
        rows = (
            db.query(CallRecording)
            .filter(CallRecording.provider_platform == "vobiz")
            .order_by(CallRecording.created_at.desc())
            .limit(200)
            .all()
        )
        for candidate in rows:
            data = candidate.call_data if isinstance(candidate.call_data, dict) else {}
            for key in ("request_uuid", "message_uuid", "api_id", "call_uuid"):
                if data.get(key) == provider_call_id:
                    return candidate
    if call_ref:
        return _find_by_call_ref(db, call_ref)
    return None


def create_inbound_call_recording(
    db: Session,
    *,
    agent: Agent,
    organization_id: UUID,
    call_ref: str,
    from_number: Optional[str],
    to_number: Optional[str],
    provider_call_id: Optional[str] = None,
    evaluator_id: Optional[UUID] = None,
    evaluator_result_id: Optional[UUID] = None,
) -> CallRecording:
    existing = find_call_recording(db, call_ref=call_ref, provider_call_id=provider_call_id)
    if existing:
        return existing

    call_short_id = "".join(random.choices(string.digits, k=6))
    call_data: Dict[str, Any] = {
        "call_ref": call_ref,
        "call_short_id": call_short_id,
        "direction": "inbound",
        "from_number": from_number,
        "to_number": to_number,
        "started_at": _now_iso(),
        "live_transcript": [],
    }
    if evaluator_id is not None:
        call_data["evaluator_id"] = str(evaluator_id)
    row = CallRecording(
        organization_id=organization_id,
        workspace_id=agent.workspace_id,
        call_short_id=call_short_id,
        status=CallRecordingStatus.PENDING,
        source=CallRecordingSource.WEBHOOK,
        call_event="call_started",
        call_data=call_data,
        provider_call_id=provider_call_id,
        provider_platform="vobiz",
        agent_id=agent.id,
        evaluator_result_id=evaluator_result_id,
    )
    db.add(row)
    db.flush()
    from app.services.live_entity_storage import register_call_recording

    register_call_recording(db, row)
    db.commit()
    db.refresh(row)

    if evaluator_result_id:
        result = (
            db.query(EvaluatorResult)
            .filter(EvaluatorResult.id == evaluator_result_id)
            .first()
        )
        if result:
            from app.services.synthetic_traces.trace_service import open_trace_for_call_recording

            open_trace_for_call_recording(db, recording=row, evaluator_result=result)

    return row


def mark_call_in_progress(
    db: Session,
    *,
    call_ref: Optional[str] = None,
    provider_call_id: Optional[str] = None,
) -> Optional[CallRecording]:
    row = find_call_recording(db, call_ref=call_ref, provider_call_id=provider_call_id)
    if not row:
        return None
    row.call_event = "call_in_progress"
    data = _copy_call_data(row)
    data.setdefault("live_transcript", [])
    if not data.get("started_at"):
        data["started_at"] = _now_iso()
    _save_call_data(db, row, data)
    from app.services.evaluators.evaluator_inbound_service import sync_linked_evaluator_result_call_state

    sync_linked_evaluator_result_call_state(db, row)
    return row


def update_call_from_vobiz_event(
    db: Session,
    *,
    provider_call_id: str,
    call_status: Optional[str],
    payload: Optional[Dict[str, Any]] = None,
    call_ref: Optional[str] = None,
) -> Optional[CallRecording]:
    row = find_call_recording(db, call_ref=call_ref, provider_call_id=provider_call_id)
    if not row:
        return None

    event = _normalize_call_event(call_status)
    data = _fresh_call_data(db, row)
    row.status = CallRecordingStatus.UPDATED
    row.call_event = event
    if payload:
        data["last_event"] = payload
    if event == "call_ended" or event == "failed":
        data["ended_at"] = _now_iso()
    _save_call_data(db, row, data)
    return row


def link_provider_call_id(
    db: Session,
    *,
    call_ref: str,
    provider_call_id: str,
) -> Optional[CallRecording]:
    if not provider_call_id:
        return None
    row = find_call_recording(db, call_ref=call_ref)
    if not row:
        return None
    data = _copy_call_data(row)
    data["call_uuid"] = provider_call_id
    if row.provider_call_id != provider_call_id:
        row.provider_call_id = provider_call_id
    _save_call_data(db, row, data)
    return row


def finalize_call_on_media_disconnect(
    db: Session,
    *,
    call_ref: str,
) -> Optional[CallRecording]:
    """Mark a live call as ended when the media websocket closes."""
    row = find_call_recording(db, call_ref=call_ref)
    if not row:
        # region agent log
        from app.utils.debug_agent_log import agent_debug_log

        agent_debug_log(
            "call_recording_lifecycle.py:finalize_call_on_media_disconnect",
            "no CallRecording for call_ref",
            {"call_ref": call_ref},
            "H3",
        )
        # endregion
        return None
    event = (row.call_event or "").lower()
    if event not in LIVE_CALL_EVENTS:
        return row
    updated = update_call_from_vobiz_event(
        db,
        provider_call_id=row.provider_call_id or "",
        call_status="completed",
        payload={"source": "media_disconnect"},
        call_ref=call_ref,
    )
    if updated:
        data = _fresh_call_data(db, updated)
        live_transcript = list(data.get("live_transcript") or [])
        if live_transcript and not data.get("messages"):
            data["messages"] = live_transcript_to_messages(live_transcript)
            _save_call_data(db, updated, data)
        # region agent log
        from app.utils.debug_agent_log import agent_debug_log

        agent_debug_log(
            "call_recording_lifecycle.py:finalize_call_on_media_disconnect",
            "call finalized on media disconnect",
            {
                "call_short_id": updated.call_short_id,
                "call_event": updated.call_event,
                "live_transcript_count": len(live_transcript),
                "messages_count": len(data.get("messages") or []),
            },
            "H3",
        )
        # endregion
        # Evaluator dispatch runs after recording artifacts exist (Celery finalize or
        # carrier recording webhook). Enqueue here only when audio is already on the row.
        if updated.evaluator_result_id:
            data_after = _fresh_call_data(db, updated)
            if data_after.get("recording_s3_key"):
                from app.services.evaluators.evaluator_inbound_service import (
                    enqueue_linked_evaluator_result_if_ready,
                )

                enqueue_linked_evaluator_result_if_ready(db, updated)
    return updated


def ingest_carrier_recording_url(
    db: Session,
    row: CallRecording,
    recording_url: str,
) -> Optional[str]:
    """Download a carrier session recording and store as recording_s3_key (preferred artifact)."""
    data = _fresh_call_data(db, row)
    if data.get("recording_s3_key") and data.get("recording_source") == "carrier":
        return str(data["recording_s3_key"])

    existing_pipeline_key = data.get("recording_s3_key")

    from loguru import logger

    from app.services.storage.s3_service import s3_service
    from app.services.telephony.recording_download import download_recording_url

    try:
        audio_bytes, content_type = download_recording_url(
            recording_url,
            user_supplied=False,
        )
    except Exception as exc:
        logger.warning(
            "Carrier recording download failed for call_short_id={}: {}",
            row.call_short_id,
            exc,
        )
        return None

    lowered = (content_type or "").lower()
    if "wav" in lowered:
        file_format = "wav"
    elif "mpeg" in lowered or "mp3" in lowered:
        file_format = "mp3"
    else:
        file_format = "mp3"

    try:
        file_id = uuid.uuid4()
        meaningful_id = f"carrier-{row.call_short_id}-{int(datetime.now(timezone.utc).timestamp())}"
        s3_key = s3_service.upload_file(
            file_content=audio_bytes,
            file_id=file_id,
            file_format=file_format,
            organization_id=str(row.organization_id),
            evaluator_id=None,
            meaningful_id=meaningful_id,
        )
    except Exception as exc:
        logger.warning(
            "Carrier recording S3 upload failed for call_short_id={}: {}",
            row.call_short_id,
            exc,
        )
        return None

    data["recording_s3_key"] = s3_key
    if existing_pipeline_key and existing_pipeline_key != s3_key:
        data["pipeline_recording_s3_key"] = existing_pipeline_key
    data["recording_source"] = "carrier"
    _save_call_data(db, row, data)

    if row.evaluator_result_id:
        from app.services.evaluators.evaluator_inbound_service import (
            enqueue_linked_evaluator_result_if_ready,
        )

        enqueue_linked_evaluator_result_if_ready(db, row)
    return s3_key


def append_live_transcript_turn(
    db: Session,
    *,
    call_short_id: str,
    role: str,
    content: str,
) -> None:
    if not content.strip():
        return
    row = db.query(CallRecording).filter(CallRecording.call_short_id == call_short_id).first()
    if not row:
        return
    data = _copy_call_data(row)
    transcript = list(data.get("live_transcript") or [])
    normalized = content.strip()
    if transcript and transcript[-1].get("role") == role:
        last_content = transcript[-1].get("content") or ""
        if normalized == last_content:
            return
        if normalized.startswith(last_content):
            transcript[-1] = {
                "role": role,
                "content": normalized,
                "timestamp": _now_iso(),
            }
            data["live_transcript"] = transcript
            _save_call_data(db, row, data)
            return
    transcript.append(
        {
            "role": role,
            "content": normalized,
            "timestamp": _now_iso(),
        }
    )
    data["live_transcript"] = transcript
    _save_call_data(db, row, data)


def persist_telephony_call_artifacts(
    db: Session,
    *,
    call_short_id: str,
    conversation_turns: Optional[list] = None,
    transcript_text: Optional[str] = None,
    s3_key: Optional[str] = None,
    duration: Optional[float] = None,
    trace_turns: Optional[list] = None,
) -> Optional[CallRecording]:
    """Persist transcript and recording metadata when a telephony call ends."""
    row = db.query(CallRecording).filter(CallRecording.call_short_id == call_short_id).first()
    if not row:
        # region agent log
        from app.utils.debug_agent_log import agent_debug_log

        agent_debug_log(
            "call_recording_lifecycle.py:persist_telephony_call_artifacts",
            "CallRecording not found",
            {"call_short_id": call_short_id},
            "H3",
        )
        # endregion
        return None

    data = _copy_call_data(row)
    live_transcript = list(data.get("live_transcript") or [])

    resolved_messages = resolve_telephony_messages(
        live_transcript=live_transcript,
        conversation_turns=conversation_turns,
    )
    if resolved_messages:
        data["messages"] = resolved_messages
        if not live_transcript:
            data["live_transcript"] = [
                {
                    "role": msg["role"],
                    "content": msg["content"],
                    "timestamp": _now_iso(),
                }
                for msg in resolved_messages
            ]

    if transcript_text:
        data["transcript"] = transcript_text
    if s3_key:
        if not data.get("recording_s3_key"):
            data["recording_s3_key"] = s3_key
        else:
            data.setdefault("pipeline_recording_s3_key", s3_key)
    if duration is not None:
        data["duration_seconds"] = duration
    if not data.get("ended_at"):
        data["ended_at"] = _now_iso()

    _save_call_data(db, row, data)
    # region agent log
    from app.utils.debug_agent_log import agent_debug_log

    agent_debug_log(
        "call_recording_lifecycle.py:persist_telephony_call_artifacts",
        "artifacts persisted",
        {
            "call_short_id": call_short_id,
            "live_transcript_count": len(data.get("live_transcript") or []),
            "messages_count": len(data.get("messages") or []),
            "has_recording_s3_key": bool(data.get("recording_s3_key")),
            "has_recording_url": bool(data.get("recording_url")),
            "duration_seconds": data.get("duration_seconds"),
        },
        "H3",
    )
    # endregion
    try:
        from app.services.synthetic_traces.trace_service import finalize_trace

        finalize_trace(db, call_short_id=call_short_id, tier1_turns=trace_turns)
    except Exception as trace_err:
        from loguru import logger

        logger.warning("Failed to finalize synthetic call trace: {}", trace_err)

    if row.evaluator_result_id:
        from app.services.evaluators.evaluator_inbound_service import (
            enqueue_linked_evaluator_result_if_ready,
        )

        enqueue_linked_evaluator_result_if_ready(db, row)
    return row
