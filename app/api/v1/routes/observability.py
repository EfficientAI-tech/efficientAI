"""Observability routes for external call ingestion and retrieval."""

import random
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.dependencies import get_api_key, get_db, get_organization_id, get_workspace_id
from app.services.billing.flexprice_service import (
    record_observability_call_evaluated,
    record_observability_call_ingested,
)
from app.models.database import (
    Agent, APIKey, CallRecording, CallRecordingStatus, CallRecordingSource,
    Evaluator, EvaluatorResult, EvaluatorResultStatus, Scenario, Workspace,
)
from app.utils.call_recordings import generate_unique_call_short_id
from app.workers.celery_app import process_evaluator_result_task

router = APIRouter(prefix="/observability", tags=["observability"])


class CallIngestionPayload(BaseModel):
    """Flat payload for ingesting a single call record from an external source."""

    id: str
    agent_id: Optional[Union[int, str]] = None
    startedAt: Optional[str] = None
    endedAt: Optional[str] = None
    to_phone_number: Optional[str] = None
    from_phone_number: Optional[str] = None
    messages: Optional[List[Dict[str, Any]]] = None
    metadata: Optional[Dict[str, Any]] = None
    endedReason: Optional[str] = None
    recording_url: Optional[str] = None
    provider_platform: Optional[str] = None

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "id": "0199e72d-795e-7ffe-b9b9-d3b08a3a11ae",
                "agent_id": 2,
                "startedAt": "2025-10-15T09:22:21.787Z",
                "endedAt": "2025-10-15T09:24:30.229Z",
                "to_phone_number": "+18646190758",
                "from_phone_number": "+14155551234",
                "messages": [
                    {
                        "role": "bot",
                        "content": "Hi there. How can I help you today?",
                        "start_time": 1760520142852,
                        "end_time": 1760520147842,
                    }
                ],
                "metadata": {"customer_name": "John Doe", "call_type": "support"},
                "endedReason": "customer-hungup",
                "recording_url": "https://storage.example.com/recordings/call_123.wav",
            }
        },
    )


def _serialize_agent_summary(agent: Optional[Agent]) -> Optional[Dict[str, Any]]:
    """Serialize a minimal agent summary for call list/detail responses."""
    if not agent:
        return None
    return {
        "id": str(agent.id),
        "agent_id": agent.agent_id,
        "name": agent.name,
    }


def _load_agents_by_id(db: Session, agent_ids: List[UUID]) -> Dict[UUID, Agent]:
    """Batch-load agents by primary key to avoid N+1 queries."""
    if not agent_ids:
        return {}
    agents = db.query(Agent).filter(Agent.id.in_(agent_ids)).all()
    return {agent.id: agent for agent in agents}


def _serialize_call_recording(
    call_recording: CallRecording,
    include_data: bool = False,
    agent: Optional[Agent] = None,
) -> Dict[str, Any]:
    """Serialize call recording for API responses."""
    call_data = call_recording.call_data if isinstance(call_recording.call_data, dict) else {}
    live_events = {
        "outbound_initiated",
        "ringing",
        "call_started",
        "call_in_progress",
        "in-progress",
        "answered",
    }
    call_event = call_recording.call_event or ""
    payload: Dict[str, Any] = {
        "id": str(call_recording.id),
        "call_short_id": call_recording.call_short_id,
        "display_name": (
            agent.name
            if agent and agent.name
            else (
                f"{call_recording.provider_platform} call"
                if call_recording.provider_platform
                else call_recording.call_short_id
            )
        ),
        "status": call_recording.status.value if call_recording.status else None,
        "call_event": call_event,
        "is_live": call_event in live_events,
        "direction": call_data.get("direction"),
        "source": call_recording.source.value if call_recording.source else None,
        "provider_platform": call_recording.provider_platform,
        "provider_call_id": call_recording.provider_call_id,
        "agent_id": str(call_recording.agent_id) if call_recording.agent_id else None,
        "agent": _serialize_agent_summary(agent),
        "created_at": call_recording.created_at.isoformat() if call_recording.created_at else None,
        "updated_at": call_recording.updated_at.isoformat() if call_recording.updated_at else None,
    }

    if include_data:
        payload["call_data"] = call_recording.call_data
    else:
        payload["live_transcript"] = call_data.get("live_transcript") or []

    return payload


def _resolve_default_workspace_id(db: Session, organization_id: UUID) -> UUID:
    """Return the org's Default workspace_id.

    Used by webhook ingestion paths where there is no authenticated session
    to supply an ``X-Workspace-Id`` header.
    """
    default_ws = (
        db.query(Workspace)
        .filter(
            Workspace.organization_id == organization_id,
            Workspace.is_default.is_(True),
        )
        .first()
    )
    if default_ws is None:
        raise HTTPException(
            status_code=500,
            detail=(
                "No default workspace exists for this organization. "
                "Migration 033 may not have run."
            ),
        )
    return default_ws.id


def _upsert_call_recording(
    *,
    db: Session,
    organization_id: UUID,
    workspace_id: UUID,
    provider_platform: str,
    provider_call_id: str,
    call_data_payload: Dict[str, Any],
    agent_ref_raw: Optional[str],
    explicit_agent_id: Optional[UUID] = None,
    call_event: Optional[str] = None,
    source: CallRecordingSource = CallRecordingSource.WEBHOOK,
) -> Dict[str, Any]:
    """Create/update a call recording for an organization + workspace.

    If the referenced agent lives in a different workspace, prefer the agent's
    workspace so the recording stays co-located with its agent for filtering.
    """
    # Attempt to link to an internal agent when a UUID is provided (unless explicit agent provided)
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
            # Not a UUID; treat as external reference only
            agent_id = None

    # Preserve external agent reference alongside provider payload
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

    if call_recording:
        call_recording.call_data = call_data_payload
        call_recording.status = CallRecordingStatus.UPDATED
        call_recording.source = source
        if call_event:
            call_recording.call_event = call_event
        if agent_id:
            call_recording.agent_id = agent_id
        db.commit()
        db.refresh(call_recording)
        action = "updated"
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
            agent_id=agent_id,
        )
        db.add(call_recording)
        db.commit()
        db.refresh(call_recording)
        action = "created"

    agent_obj = None
    if call_recording.agent_id:
        agent_obj = db.query(Agent).filter(Agent.id == call_recording.agent_id).first()

    response = _serialize_call_recording(call_recording, include_data=True, agent=agent_obj)
    response["action"] = action
    if action == "created":
        record_observability_call_ingested(
            organization_id,
            call_recording.call_short_id,
            workspace_id=workspace_id,
            provider=provider_platform,
        )
    return response


def _validate_webhook_api_key(api_key: str, db: Session) -> UUID:
    """Validate an API key from a webhook URL and return the organization ID."""
    db_key = db.query(APIKey).filter(
        APIKey.key == api_key, APIKey.is_active == True  # noqa: E712
    ).first()
    if not db_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive API key",
        )
    db_key.last_used = datetime.utcnow()
    db.commit()
    return db_key.organization_id


def _process_flat_payload(body: Dict[str, Any], organization_id: UUID, db: Session) -> Dict[str, Any]:
    """Process a flat CallIngestionPayload-style body in the org's default workspace."""
    payload = CallIngestionPayload.model_validate(body)

    provider_call_id = payload.id
    provider_platform = (payload.provider_platform or "external").lower().strip()

    call_data_payload: Dict[str, Any] = {}
    for field in (
        "startedAt", "endedAt", "to_phone_number", "from_phone_number",
        "messages", "metadata", "endedReason", "recording_url",
    ):
        value = getattr(payload, field, None)
        if value is not None:
            call_data_payload[field] = value

    if payload.model_extra:
        call_data_payload.update(payload.model_extra)

    agent_ref_raw = str(payload.agent_id) if payload.agent_id is not None else None

    call_event: Optional[str] = None
    if payload.endedAt:
        call_event = "call_ended"
    elif payload.startedAt:
        call_event = "call_started"

    workspace_id = _resolve_default_workspace_id(db, organization_id)

    return _upsert_call_recording(
        db=db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        provider_platform=provider_platform,
        provider_call_id=provider_call_id,
        call_data_payload=call_data_payload,
        agent_ref_raw=agent_ref_raw,
        call_event=call_event,
        source=CallRecordingSource.WEBHOOK,
    )


def _process_provider_payload(body: Dict[str, Any], organization_id: UUID, db: Session) -> Dict[str, Any]:
    """Process a provider webhook payload in the org's default workspace."""
    call_payload = body.get("call") or body.get("call_data")
    if not call_payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="call or call_data is required in provider webhook payload",
        )

    agent_ref_raw = body.get("agent_id") or call_payload.get("agent_id")
    provider_call_id = (
        body.get("provider_call_id")
        or call_payload.get("call_id")
        or call_payload.get("id")
    )
    if not provider_call_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="provider_call_id (or call.call_id / call.id) is required",
        )

    provider_platform = (
        body.get("provider_platform")
        or call_payload.get("provider_platform")
        or "external"
    ).lower().strip()

    call_data_payload = dict(call_payload)
    call_event = body.get("event") or call_data_payload.pop("_event", None)

    workspace_id = _resolve_default_workspace_id(db, organization_id)

    return _upsert_call_recording(
        db=db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        provider_platform=provider_platform,
        provider_call_id=provider_call_id,
        call_data_payload=call_data_payload,
        agent_ref_raw=str(agent_ref_raw) if agent_ref_raw else None,
        call_event=call_event,
        source=CallRecordingSource.WEBHOOK,
    )


@router.post("/calls/webhook/retell/{api_key}", status_code=status.HTTP_201_CREATED)
async def ingest_retell_webhook(
    api_key: str,
    body: Dict[str, Any],
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Retell-specific webhook — API key embedded in the URL.

    Usage:
        POST https://your-domain.com/api/v1/observability/calls/webhook/retell/<YOUR_API_KEY>

    Accepts Retell's native webhook payload format:
    ``{"event": "call_ended", "call": {...}}``
    """
    organization_id = _validate_webhook_api_key(api_key, db)
    return _process_provider_payload(body, organization_id, db)


@router.post("/calls/webhook/{api_key}", status_code=status.HTTP_201_CREATED)
async def ingest_call_via_webhook_url(
    api_key: str,
    body: Dict[str, Any],
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Generic webhook — API key embedded in the URL (Slack-style).

    Usage:
        POST https://your-domain.com/api/v1/observability/calls/webhook/<YOUR_API_KEY>

    Accepts the flat call ingestion format:
    ``{"id": "...", "messages": [...], "startedAt": "...", ...}``
    """
    organization_id = _validate_webhook_api_key(api_key, db)
    return _process_flat_payload(body, organization_id, db)



@router.get("/calls", response_model=List[Dict[str, Any]])
async def list_calls(
    skip: int = 0,
    limit: int = 100,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """List ingested call records in the active workspace."""
    del api_key  # Dependency enforcement only

    call_recordings = (
        db.query(CallRecording)
        .filter(
            CallRecording.organization_id == organization_id,
            CallRecording.workspace_id == workspace_id,
            CallRecording.source == CallRecordingSource.WEBHOOK,
        )
        .order_by(CallRecording.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    from app.services.live_entity_storage import hydrate_call_recordings

    hydrate_call_recordings(call_recordings)

    agent_ids = [cr.agent_id for cr in call_recordings if cr.agent_id]
    agents_by_id = _load_agents_by_id(db, agent_ids)

    return [
        _serialize_call_recording(cr, agent=agents_by_id.get(cr.agent_id) if cr.agent_id else None)
        for cr in call_recordings
    ]


@router.get("/calls/{call_short_id}", response_model=Dict[str, Any])
async def get_call(
    call_short_id: str,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Retrieve a specific call in the active workspace by its short ID."""
    del api_key  # Dependency enforcement only

    call_recording = (
        db.query(CallRecording)
        .filter(
            CallRecording.call_short_id == call_short_id,
            CallRecording.organization_id == organization_id,
            CallRecording.workspace_id == workspace_id,
            CallRecording.source == CallRecordingSource.WEBHOOK,
        )
        .first()
    )

    if not call_recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call not found",
        )

    from app.services.live_entity_storage import hydrate_call_recordings

    hydrate_call_recordings([call_recording])

    # region agent log
    from app.utils.debug_agent_log import agent_debug_log

    call_data_dbg = call_recording.call_data if isinstance(call_recording.call_data, dict) else {}
    agent_debug_log(
        "observability.py:get_call",
        "call detail fetched",
        {
            "call_short_id": call_short_id,
            "call_event": call_recording.call_event,
            "live_transcript_count": len(call_data_dbg.get("live_transcript") or []),
            "messages_count": len(call_data_dbg.get("messages") or []),
            "has_recording_s3_key": bool(call_data_dbg.get("recording_s3_key")),
            "has_recording_url": bool(call_data_dbg.get("recording_url")),
        },
        "H5",
    )
    # endregion

    agent = None
    if call_recording.agent_id:
        agent = db.query(Agent).filter(Agent.id == call_recording.agent_id).first()

    return _serialize_call_recording(call_recording, include_data=True, agent=agent)


@router.get("/calls/{call_short_id}/live-events")
async def stream_call_live_events(
    call_short_id: str,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Server-sent events stream for live transcript turns during an active call."""
    import asyncio
    import json

    from fastapi.responses import StreamingResponse

    del api_key

    call_recording = (
        db.query(CallRecording)
        .filter(
            CallRecording.call_short_id == call_short_id,
            CallRecording.organization_id == organization_id,
            CallRecording.workspace_id == workspace_id,
            CallRecording.source == CallRecordingSource.WEBHOOK,
        )
        .first()
    )
    if not call_recording:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")

    bound_recording_id = call_recording.id
    bound_org_id = organization_id
    bound_workspace_id = workspace_id

    live_events = {
        "outbound_initiated",
        "ringing",
        "call_started",
        "call_in_progress",
        "in-progress",
        "answered",
    }

    async def event_generator():
        from app.database import SessionLocal

        seen = 0
        while True:
            session = SessionLocal()
            try:
                row = (
                    session.query(CallRecording)
                    .filter(
                        CallRecording.id == bound_recording_id,
                        CallRecording.call_short_id == call_short_id,
                        CallRecording.organization_id == bound_org_id,
                        CallRecording.workspace_id == bound_workspace_id,
                        CallRecording.source == CallRecordingSource.WEBHOOK,
                    )
                    .first()
                )
                if not row:
                    break
                data = row.call_data if isinstance(row.call_data, dict) else {}
                transcript = data.get("live_transcript") or []
                if len(transcript) > seen:
                    for entry in transcript[seen:]:
                        yield f"data: {json.dumps(entry)}\n\n"
                    seen = len(transcript)
                if (row.call_event or "") not in live_events:
                    break
            finally:
                session.close()
            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/calls/{call_short_id}/audio")
async def stream_observability_call_audio(
    call_short_id: str,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Stream call recording audio for observability calls (S3 or provider URL)."""
    from io import BytesIO

    from fastapi.responses import RedirectResponse, StreamingResponse

    del api_key

    call_recording = (
        db.query(CallRecording)
        .filter(
            CallRecording.call_short_id == call_short_id,
            CallRecording.organization_id == organization_id,
            CallRecording.workspace_id == workspace_id,
            CallRecording.source == CallRecordingSource.WEBHOOK,
        )
        .first()
    )
    if not call_recording:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")

    call_data = call_recording.call_data if isinstance(call_recording.call_data, dict) else {}
    recording_url = call_data.get("recording_url")
    if recording_url:
        return RedirectResponse(recording_url)

    s3_key = (
        call_data.get("stereo_recording_s3_key")
        or call_data.get("recording_s3_key")
        or call_data.get("mono_recording_s3_key")
    )
    if not s3_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No recording available")

    # region agent log
    from app.utils.debug_agent_log import agent_debug_log

    agent_debug_log(
        "observability.py:stream_observability_call_audio",
        "serving observability audio",
        {
            "call_short_id": call_short_id,
            "has_recording_s3_key": True,
            "has_recording_url": bool(recording_url),
        },
        "H6",
        run_id="post-fix",
    )
    # endregion

    from app.services.storage.s3_service import s3_service

    if not s3_service.is_enabled():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="S3 storage is not configured")

    try:
        audio_bytes = s3_service.download_file_by_key(s3_key)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio file not found in storage") from exc

    extension = s3_key.rsplit(".", 1)[-1].lower() if "." in s3_key else "wav"
    content_type_map = {"webm": "audio/webm", "mp3": "audio/mpeg", "wav": "audio/wav", "ogg": "audio/ogg"}
    content_type = content_type_map.get(extension, "audio/wav")

    return StreamingResponse(
        BytesIO(audio_bytes),
        media_type=content_type,
        headers={
            "Content-Disposition": f'inline; filename="call_{call_short_id}.{extension}"',
        },
    )


@router.delete("/calls/{call_short_id}", response_model=Dict[str, Any])
async def delete_call(
    call_short_id: str,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Delete a webhook ingested call recording in the active workspace."""
    del api_key  # Dependency enforcement only

    call_recording = (
        db.query(CallRecording)
        .filter(
            CallRecording.call_short_id == call_short_id,
            CallRecording.organization_id == organization_id,
            CallRecording.workspace_id == workspace_id,
            CallRecording.source == CallRecordingSource.WEBHOOK,
        )
        .first()
    )

    if not call_recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call not found",
        )

    db.delete(call_recording)
    db.commit()

    return {"message": "Call deleted"}


class EvaluateCallPayload(BaseModel):
    """Payload to trigger evaluation on an ingested call."""

    evaluator_id: str


def _messages_to_transcript(messages: List[Dict[str, Any]]) -> str:
    """Convert a list of message dicts to a plain-text transcript."""
    lines: List[str] = []
    for msg in messages:
        role = str(msg.get("role", "unknown")).lower()
        if role in {"bot", "assistant", "agent"}:
            label = "Agent"
        elif role == "user":
            label = "Caller"
        else:
            label = role.capitalize()
        lines.append(f"{label}: {msg.get('content', '')}")
    return "\n".join(lines)


def _resolve_call_duration_seconds(call_data: Dict[str, Any]) -> Optional[float]:
    """Resolve duration from observability or telephony call_data shapes."""
    duration = call_data.get("duration_seconds")
    if isinstance(duration, (int, float)) and duration > 0:
        return float(duration)

    started_raw = call_data.get("startedAt") or call_data.get("started_at")
    ended_raw = call_data.get("endedAt") or call_data.get("ended_at")
    if started_raw and ended_raw:
        try:
            started = datetime.fromisoformat(str(started_raw).replace("Z", "+00:00"))
            ended = datetime.fromisoformat(str(ended_raw).replace("Z", "+00:00"))
            diff = (ended - started).total_seconds()
            if diff > 0:
                return diff
        except (ValueError, TypeError):
            pass

    duration_ms = call_data.get("duration_ms")
    if isinstance(duration_ms, (int, float)) and duration_ms > 0:
        return float(duration_ms) / 1000.0
    return None


def _messages_to_speaker_segments(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert messages to speaker_segments format expected by the evaluation UI."""
    segments: List[Dict[str, Any]] = []
    for index, msg in enumerate(messages):
        role = str(msg.get("role", "unknown")).lower()
        if role == "user":
            speaker = "Speaker 1"
        elif role in {"bot", "assistant", "agent"}:
            speaker = "Speaker 2"
        else:
            speaker = "Speaker 2"
        start = msg.get("start_time", 0)
        end = msg.get("end_time", 0)
        if isinstance(start, (int, float)) and start > 1e10:
            start = start / 1000.0
        if isinstance(end, (int, float)) and end > 1e10:
            end = end / 1000.0
        if not end and isinstance(start, (int, float)):
            end = start
        if not start and not end:
            start = float(index)
            end = float(index)
        segments.append({
            "speaker": speaker,
            "text": msg.get("content", ""),
            "start": float(start),
            "end": float(end),
        })
    return segments


@router.post("/calls/{call_short_id}/evaluate", status_code=status.HTTP_201_CREATED)
async def evaluate_call(
    call_short_id: str,
    payload: EvaluateCallPayload,
    background_tasks: BackgroundTasks,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Trigger an LLM evaluation on an ingested call in the active workspace.

    Both the call recording and the evaluator must already live in the same
    workspace as the caller.
    """
    del api_key

    call_recording = (
        db.query(CallRecording)
        .filter(
            CallRecording.call_short_id == call_short_id,
            CallRecording.organization_id == organization_id,
            CallRecording.workspace_id == workspace_id,
            CallRecording.source == CallRecordingSource.WEBHOOK,
        )
        .first()
    )
    if not call_recording:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")

    call_data = dict(call_recording.call_data or {})
    call_data.setdefault("call_short_id", call_recording.call_short_id)
    messages = call_data.get("messages")
    if not messages or not isinstance(messages, list) or len(messages) == 0:
        live_transcript = call_data.get("live_transcript")
        if isinstance(live_transcript, list) and live_transcript:
            from app.services.telephony.call_recording_lifecycle import live_transcript_to_messages

            messages = live_transcript_to_messages(live_transcript)
            call_data["messages"] = messages
    if not messages or not isinstance(messages, list) or len(messages) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Call has no messages to evaluate",
        )

    try:
        evaluator_uuid = UUID(payload.evaluator_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid evaluator_id")

    evaluator = (
        db.query(Evaluator)
        .filter(
            Evaluator.id == evaluator_uuid,
            Evaluator.organization_id == organization_id,
            Evaluator.workspace_id == workspace_id,
        )
        .first()
    )
    if not evaluator:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluator not found")

    is_custom = bool(evaluator.custom_prompt) or evaluator.agent_id is None
    if is_custom:
        result_name = evaluator.name or "Custom Evaluation"
    else:
        scenario = db.query(Scenario).filter(Scenario.id == evaluator.scenario_id).first()
        result_name = scenario.name if scenario else "Unknown Scenario"

    result_id: Optional[str] = None
    for _ in range(100):
        candidate = f"{random.randint(100000, 999999)}"
        if not db.query(EvaluatorResult).filter(EvaluatorResult.result_id == candidate).first():
            result_id = candidate
            break
    if not result_id:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to generate unique result ID")

    transcript = _messages_to_transcript(messages)
    duration_seconds = _resolve_call_duration_seconds(call_data)
    audio_s3_key = call_data.get("recording_s3_key")

    evaluator_result = EvaluatorResult(
        result_id=result_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
        evaluator_id=evaluator.id,
        agent_id=evaluator.agent_id,
        persona_id=evaluator.persona_id,
        scenario_id=evaluator.scenario_id,
        name=result_name,
        duration_seconds=duration_seconds,
        status=EvaluatorResultStatus.QUEUED.value,
        transcription=transcript,
        speaker_segments=_messages_to_speaker_segments(messages),
        audio_s3_key=audio_s3_key,
        provider_call_id=call_recording.provider_call_id,
        provider_platform=call_recording.provider_platform,
        call_data=call_data,
    )

    db.add(evaluator_result)
    db.commit()
    db.refresh(evaluator_result)

    call_recording.evaluator_result_id = evaluator_result.id
    db.commit()

    try:
        task = process_evaluator_result_task.delay(str(evaluator_result.id))
        evaluator_result.celery_task_id = task.id
        db.commit()
    except Exception:
        pass

    background_tasks.add_task(
        record_observability_call_evaluated,
        organization_id,
        call_short_id,
        workspace_id=workspace_id,
    )

    return {
        "evaluator_result_id": str(evaluator_result.id),
        "result_id": evaluator_result.result_id,
        "status": evaluator_result.status,
        "message": "Evaluation queued successfully",
    }


from app.core.auth.capabilities import REPORTS_GENERATE, REPORTS_VIEW
from app.core.auth.workspace_route_capabilities import apply_workspace_route_capabilities

apply_workspace_route_capabilities(
    router,
    view_capability=REPORTS_VIEW,
    manage_capability=REPORTS_GENERATE,
    run_capability=REPORTS_GENERATE,
)

