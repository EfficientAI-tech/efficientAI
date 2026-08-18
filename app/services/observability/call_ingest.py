"""Call recording ingest helpers for observability."""

from datetime import UTC, datetime
from typing import Any, Dict, Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import (
    Agent,
    CallRecording,
    CallRecordingSource,
    CallRecordingStatus,
)
from app.services.observability.live_ingest import (
    derive_live_call_event,
    merge_live_event_call_data,
)
from app.services.billing.flexprice_service import record_observability_call_ingested
from app.utils.call_recordings import generate_unique_call_short_id

# Sources surfaced in the Observability UI/API (webhooks + live playground/voice bundle).
OBSERVABILITY_CALL_SOURCES: Tuple[CallRecordingSource, ...] = (
    CallRecordingSource.WEBHOOK,
    CallRecordingSource.PLAYGROUND,
)


def upsert_call_recording(
    *,
    db: Session,
    organization_id: UUID,
    workspace_id: UUID,
    provider_platform: str,
    provider_call_id: str,
    call_data_payload: Dict[str, Any],
    agent_ref_raw: Optional[str] = None,
    explicit_agent_id: Optional[UUID] = None,
    call_event: Optional[str] = None,
    trace_id: Optional[str] = None,
    evaluator_result_id: Optional[UUID] = None,
    source: CallRecordingSource = CallRecordingSource.WEBHOOK,
) -> tuple[CallRecording, str]:
    """Create or update a call recording for an organization + workspace."""
    agent_id: Optional[UUID] = explicit_agent_id
    if not agent_id and agent_ref_raw:
        try:
            agent_uuid = UUID(agent_ref_raw)
            agent = (
                db.query(Agent)
                .filter(Agent.id == agent_uuid, Agent.organization_id == organization_id)
                .first()
            )
            if agent:
                agent_id = agent.id
                if agent.workspace_id and agent.workspace_id != workspace_id:
                    workspace_id = agent.workspace_id
        except ValueError:
            agent_id = None

    if agent_ref_raw:
        call_data_payload.setdefault("_agent_ref", agent_ref_raw)

    call_recording = (
        db.query(CallRecording)
        .filter(
            CallRecording.organization_id == organization_id,
            CallRecording.provider_call_id == provider_call_id,
            CallRecording.provider_platform == provider_platform,
        )
        .first()
    )

    created = call_recording is None
    if call_recording:
        call_recording.call_data = call_data_payload
        call_recording.status = CallRecordingStatus.UPDATED
        call_recording.source = source
        if trace_id:
            call_recording.trace_id = trace_id
        if call_event:
            call_recording.call_event = call_event
        if agent_id:
            call_recording.agent_id = agent_id
        if evaluator_result_id:
            call_recording.evaluator_result_id = evaluator_result_id
    else:
        call_recording = CallRecording(
            organization_id=organization_id,
            workspace_id=workspace_id,
            call_short_id=generate_unique_call_short_id(db),
            status=CallRecordingStatus.UPDATED,
            call_event=call_event,
            source=source,
            call_data=call_data_payload,
            provider_call_id=provider_call_id,
            provider_platform=provider_platform,
            trace_id=trace_id,
            agent_id=agent_id,
            evaluator_result_id=evaluator_result_id,
        )
        db.add(call_recording)

    db.commit()
    db.refresh(call_recording)

    if created:
        record_observability_call_ingested(
            organization_id,
            call_recording.call_short_id,
            workspace_id=workspace_id,
            provider=provider_platform,
        )

    return call_recording, ("created" if created else "updated")


def persist_playground_voice_call(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    agent_id: UUID,
    result_id: str,
    call_metadata: Dict[str, Any],
    evaluator_result_id: Optional[UUID] = None,
    provider_platform: str = "efficientai",
) -> Optional[CallRecording]:
    """Upsert a playground/live voice call into observability with trace linkage."""
    if not call_metadata:
        return None

    existing = (
        db.query(CallRecording)
        .filter(
            CallRecording.organization_id == organization_id,
            CallRecording.provider_call_id == result_id,
            CallRecording.provider_platform == provider_platform,
        )
        .first()
    )
    existing_data = existing.call_data if existing and isinstance(existing.call_data, dict) else {}

    call_data_payload: Dict[str, Any] = {
        "direction": "inbound",
        "evaluator_result_id": result_id,
    }

    started_at = existing_data.get("startedAt") or existing_data.get("started_at")
    if started_at:
        call_data_payload["startedAt"] = started_at
    call_data_payload["endedAt"] = datetime.now(UTC).isoformat()

    duration = call_metadata.get("duration")
    if duration is not None:
        call_data_payload["duration_seconds"] = duration

    s3_key = call_metadata.get("s3_key")
    if s3_key:
        call_data_payload["recording_s3_key"] = s3_key
    elif existing_data.get("recording_s3_key"):
        call_data_payload["recording_s3_key"] = existing_data["recording_s3_key"]

    transcription = call_metadata.get("transcription")
    speaker_segments = call_metadata.get("speaker_segments")
    if transcription:
        call_data_payload["transcription"] = transcription
    if speaker_segments:
        call_data_payload["speaker_segments"] = speaker_segments

    live_transcript = list(existing_data.get("live_transcript") or [])
    if live_transcript:
        call_data_payload["live_transcript"] = live_transcript

    from app.services.telephony.call_recording_lifecycle import resolve_telephony_messages

    resolved_messages = resolve_telephony_messages(
        live_transcript=live_transcript,
        conversation_turns=speaker_segments,
    )
    if resolved_messages:
        call_data_payload["messages"] = resolved_messages
    elif transcription:
        call_data_payload["messages"] = [{"role": "user", "content": transcription}]
        if not live_transcript:
            call_data_payload["live_transcript"] = call_data_payload["messages"]
    elif existing_data.get("messages"):
        call_data_payload["messages"] = existing_data["messages"]

    if call_metadata.get("error"):
        call_data_payload["error"] = call_metadata["error"]
        call_data_payload["endedReason"] = str(call_metadata["error"])

    trace_id = call_metadata.get("trace_id") or existing_data.get("trace_id")
    if trace_id:
        call_data_payload["trace_id"] = trace_id
    call_event = "call_failed" if call_metadata.get("error") else "call_ended"

    call_recording, _action = upsert_call_recording(
        db=db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        provider_platform=provider_platform,
        provider_call_id=result_id,
        call_data_payload=call_data_payload,
        explicit_agent_id=agent_id,
        call_event=call_event,
        trace_id=trace_id,
        evaluator_result_id=evaluator_result_id,
        source=CallRecordingSource.PLAYGROUND,
    )
    return call_recording


def upsert_live_event_call_recording(
    *,
    db: Session,
    organization_id: UUID,
    workspace_id: UUID,
    provider_platform: str,
    provider_call_id: str,
    live_event: Dict[str, Any],
    max_out_of_order_seq: int,
    agent_ref_raw: Optional[str] = None,
    explicit_agent_id: Optional[UUID] = None,
    source: CallRecordingSource = CallRecordingSource.WEBHOOK,
    persist: bool = True,
) -> tuple[CallRecording, str]:
    """Upsert a call recording by incrementally merging a live event envelope."""
    agent_id: Optional[UUID] = explicit_agent_id
    if not agent_id and agent_ref_raw:
        try:
            agent_uuid = UUID(agent_ref_raw)
            agent = (
                db.query(Agent)
                .filter(Agent.id == agent_uuid, Agent.organization_id == organization_id)
                .first()
            )
            if agent:
                agent_id = agent.id
                if agent.workspace_id and agent.workspace_id != workspace_id:
                    workspace_id = agent.workspace_id
        except ValueError:
            agent_id = None

    event_type = str(live_event.get("event_type") or "").strip().lower()
    call_event = derive_live_call_event(event_type)
    trace_id = live_event.get("trace_id")

    call_recording = (
        db.query(CallRecording)
        .filter(
            CallRecording.organization_id == organization_id,
            CallRecording.provider_call_id == provider_call_id,
            CallRecording.provider_platform == provider_platform,
        )
        .first()
    )

    created = call_recording is None
    if call_recording is None:
        call_recording = CallRecording(
            organization_id=organization_id,
            workspace_id=workspace_id,
            call_short_id=generate_unique_call_short_id(db),
            status=CallRecordingStatus.UPDATED,
            call_event=call_event,
            source=source,
            call_data={},
            provider_call_id=provider_call_id,
            provider_platform=provider_platform,
            trace_id=str(trace_id) if trace_id else None,
            agent_id=agent_id,
        )
        db.add(call_recording)
        db.flush()
    else:
        call_recording.status = CallRecordingStatus.UPDATED
        call_recording.call_event = call_event
        call_recording.source = source
        if trace_id:
            call_recording.trace_id = str(trace_id)
        if agent_id:
            call_recording.agent_id = agent_id

    merged_call_data = merge_live_event_call_data(
        existing_call_data=call_recording.call_data if isinstance(call_recording.call_data, dict) else {},
        event=live_event,
        max_out_of_order_seq=max_out_of_order_seq,
    )
    if agent_ref_raw:
        merged_call_data.setdefault("_agent_ref", agent_ref_raw)
    if trace_id and not merged_call_data.get("trace_id"):
        merged_call_data["trace_id"] = trace_id
    call_recording.call_data = merged_call_data

    if persist:
        db.commit()
        db.refresh(call_recording)

    if created and persist:
        record_observability_call_ingested(
            organization_id,
            call_recording.call_short_id,
            workspace_id=workspace_id,
            provider=provider_platform,
        )

    return call_recording, ("created" if created else "updated")
