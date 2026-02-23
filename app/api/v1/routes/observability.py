"""Observability routes for external call ingestion and retrieval."""

import random
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_api_key, get_db, get_organization_id
from app.models.database import (
    Agent, APIKey, CallRecording, CallRecordingStatus, CallRecordingSource,
    Evaluator, EvaluatorResult, EvaluatorResultStatus, Scenario,
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

    class Config:
        extra = "allow"
        json_schema_extra = {
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
        }


def _serialize_call_recording(call_recording: CallRecording, include_data: bool = False) -> Dict[str, Any]:
    """Serialize call recording for API responses."""
    payload: Dict[str, Any] = {
        "id": str(call_recording.id),
        "call_short_id": call_recording.call_short_id,
        "status": call_recording.status.value if call_recording.status else None,
        "call_event": call_recording.call_event,
        "source": call_recording.source.value if call_recording.source else None,
        "provider_platform": call_recording.provider_platform,
        "provider_call_id": call_recording.provider_call_id,
        "agent_id": str(call_recording.agent_id) if call_recording.agent_id else None,
        "created_at": call_recording.created_at.isoformat() if call_recording.created_at else None,
        "updated_at": call_recording.updated_at.isoformat() if call_recording.updated_at else None,
    }

    if include_data:
        payload["call_data"] = call_recording.call_data

    return payload


def _upsert_call_recording(
    *,
    db: Session,
    organization_id: UUID,
    provider_platform: str,
    provider_call_id: str,
    call_data_payload: Dict[str, Any],
    agent_ref_raw: Optional[str],
    explicit_agent_id: Optional[UUID] = None,
    call_event: Optional[str] = None,
    source: CallRecordingSource = CallRecordingSource.WEBHOOK,
) -> Dict[str, Any]:
    """Create/update a call recording for an organization."""
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

    response = _serialize_call_recording(call_recording, include_data=True)
    response["action"] = action
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
    """Process a flat CallIngestionPayload-style body."""
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

    return _upsert_call_recording(
        db=db,
        organization_id=organization_id,
        provider_platform=provider_platform,
        provider_call_id=provider_call_id,
        call_data_payload=call_data_payload,
        agent_ref_raw=agent_ref_raw,
        call_event=call_event,
        source=CallRecordingSource.WEBHOOK,
    )


def _process_provider_payload(body: Dict[str, Any], organization_id: UUID, db: Session) -> Dict[str, Any]:
    """Process a provider webhook payload (Retell / Vapi / generic with call or call_data key)."""
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

    return _upsert_call_recording(
        db=db,
        organization_id=organization_id,
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
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """List ingested call records for the organization."""
    del api_key  # Dependency enforcement only

    call_recordings = (
        db.query(CallRecording)
        .filter(
            CallRecording.organization_id == organization_id,
            CallRecording.source == CallRecordingSource.WEBHOOK,
        )
        .order_by(CallRecording.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return [_serialize_call_recording(cr) for cr in call_recordings]


@router.get("/calls/{call_short_id}", response_model=Dict[str, Any])
async def get_call(
    call_short_id: str,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Retrieve a specific call by its short ID, including stored payload."""
    del api_key  # Dependency enforcement only

    call_recording = (
        db.query(CallRecording)
        .filter(
            CallRecording.call_short_id == call_short_id,
            CallRecording.organization_id == organization_id,
            CallRecording.source == CallRecordingSource.WEBHOOK,
        )
        .first()
    )

    if not call_recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call not found",
        )

    return _serialize_call_recording(call_recording, include_data=True)


@router.delete("/calls/{call_short_id}", response_model=Dict[str, Any])
async def delete_call(
    call_short_id: str,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Delete a webhook ingested call recording by its short ID."""
    del api_key  # Dependency enforcement only

    call_recording = (
        db.query(CallRecording)
        .filter(
            CallRecording.call_short_id == call_short_id,
            CallRecording.organization_id == organization_id,
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
        role = msg.get("role", "unknown")
        label = "Agent" if role == "bot" else "Caller" if role == "user" else role.capitalize()
        lines.append(f"{label}: {msg.get('content', '')}")
    return "\n".join(lines)


def _messages_to_speaker_segments(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert messages to speaker_segments format expected by the evaluation UI."""
    segments: List[Dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role", "unknown")
        speaker = "Speaker 0" if role == "bot" else "Speaker 1"
        start = msg.get("start_time", 0)
        end = msg.get("end_time", 0)
        if isinstance(start, (int, float)) and start > 1e10:
            start = start / 1000.0
        if isinstance(end, (int, float)) and end > 1e10:
            end = end / 1000.0
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
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Trigger an LLM evaluation on an ingested call using the specified evaluator.

    The call must have messages in its call_data. A transcript is built from those
    messages and an EvaluatorResult is created and queued for evaluation.
    """
    del api_key

    call_recording = (
        db.query(CallRecording)
        .filter(
            CallRecording.call_short_id == call_short_id,
            CallRecording.organization_id == organization_id,
            CallRecording.source == CallRecordingSource.WEBHOOK,
        )
        .first()
    )
    if not call_recording:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")

    call_data = call_recording.call_data or {}
    messages = call_data.get("messages")
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
        .filter(Evaluator.id == evaluator_uuid, Evaluator.organization_id == organization_id)
        .first()
    )
    if not evaluator:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluator not found")

    is_custom = bool(evaluator.custom_prompt)
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
    speaker_segments = _messages_to_speaker_segments(messages)

    duration_seconds: Optional[float] = None
    if call_data.get("startedAt") and call_data.get("endedAt"):
        try:
            started = datetime.fromisoformat(call_data["startedAt"].replace("Z", "+00:00"))
            ended = datetime.fromisoformat(call_data["endedAt"].replace("Z", "+00:00"))
            duration_seconds = (ended - started).total_seconds()
        except (ValueError, TypeError):
            pass

    evaluator_result = EvaluatorResult(
        result_id=result_id,
        organization_id=organization_id,
        evaluator_id=evaluator.id,
        agent_id=evaluator.agent_id,
        persona_id=evaluator.persona_id,
        scenario_id=evaluator.scenario_id,
        name=result_name,
        duration_seconds=duration_seconds,
        status=EvaluatorResultStatus.QUEUED.value,
        transcription=transcript,
        speaker_segments=speaker_segments,
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

    return {
        "evaluator_result_id": str(evaluator_result.id),
        "result_id": evaluator_result.result_id,
        "status": evaluator_result.status,
        "message": "Evaluation queued successfully",
    }

