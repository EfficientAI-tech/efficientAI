"""Observability routes for external call ingestion and retrieval."""

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_api_key, get_db, get_organization_id
from app.models.database import Agent, CallRecording, CallRecordingStatus, CallRecordingSource
from app.utils.call_recordings import generate_unique_call_short_id

router = APIRouter(prefix="/observability", tags=["observability"])


class CallWebhookPayload(BaseModel):
    """Payload accepted from voice AI provider webhooks (Retell-style or generic)."""

    # Generic fields (optional to support multiple provider shapes)
    provider_platform: Optional[str] = None
    provider_call_id: Optional[str] = None
    # Accept provider agent IDs as free-form strings; we'll attempt UUID linking when possible
    agent_id: Optional[str] = None
    call_data: Optional[Dict[str, Any]] = None

    # Retell-style webhook fields
    event: Optional[str] = None
    call: Optional[Dict[str, Any]] = None

    @classmethod
    def _extract_call_payload(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        call_payload = values.get("call") or values.get("call_data")
        if not call_payload:
            raise ValueError("call or call_data is required")
        return call_payload

    @classmethod
    def _extract_agent_ref(cls, values: Dict[str, Any], call_payload: Dict[str, Any]) -> Optional[str]:
        return values.get("agent_id") or call_payload.get("agent_id")

    @classmethod
    def _extract_provider_call_id(cls, values: Dict[str, Any], call_payload: Dict[str, Any]) -> Optional[str]:
        return values.get("provider_call_id") or call_payload.get("call_id") or call_payload.get("id")

    @classmethod
    def _extract_provider_platform(cls, values: Dict[str, Any], call_payload: Dict[str, Any]) -> Optional[str]:
        platform = (
            values.get("provider_platform")
            or call_payload.get("provider_platform")
            or call_payload.get("platform")
            or call_payload.get("source_platform")
        )
        return platform

    @classmethod
    def _normalized_call_data(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        call_payload = cls._extract_call_payload(values)
        normalized = dict(call_payload)

        # Preserve event for traceability
        event = values.get("event")
        if event:
            normalized.setdefault("_event", event)

        agent_ref = cls._extract_agent_ref(values, call_payload)
        if agent_ref:
            normalized.setdefault("_agent_ref", agent_ref)

        return normalized

    @classmethod
    def model_validate(cls, obj: Any, *args: Any, **kwargs: Any) -> "CallWebhookPayload":
        # Let BaseModel parse first, then enrich defaults for downstream use
        parsed: CallWebhookPayload = super().model_validate(obj, *args, **kwargs)
        call_payload = cls._extract_call_payload(parsed.__dict__)
        parsed.call_data = cls._normalized_call_data(parsed.__dict__)
        parsed.provider_call_id = cls._extract_provider_call_id(parsed.__dict__, call_payload)
        parsed.provider_platform = cls._extract_provider_platform(parsed.__dict__, call_payload)
        parsed.agent_id = cls._extract_agent_ref(parsed.__dict__, call_payload)
        return parsed

    class Config:
        json_schema_extra = {
            "example": {
                "provider_platform": "retell",
                "provider_call_id": "call_123",
                "agent_id": "123e4567-e89b-12d3-a456-426614174000",
                "call_data": {"event": "call_ended", "duration": 120},
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


@router.post("/calls", status_code=status.HTTP_201_CREATED)
async def ingest_call_event(
    payload: CallWebhookPayload,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Ingest call events from voice AI providers (e.g., Retell, Vapi) via webhook.

    The caller must include the `X-EFFICIENTAI-API-KEY` (or legacy `X-API-Key`) header.
    """
    del api_key  # Dependency enforcement only

    if not payload.provider_platform:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="provider_platform is required",
        )

    provider_platform = payload.provider_platform.lower().strip()

    call_data_payload = dict(payload.call_data or {})
    agent_ref_raw = payload.agent_id
    call_event = call_data_payload.get("_event") or payload.event

    provider_call_id = payload.provider_call_id
    if not provider_call_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="provider_call_id (or call.call_id) is required",
        )

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


@router.post("/calls/retell/webhook", status_code=status.HTTP_201_CREATED)
async def ingest_retell_webhook(
    payload: CallWebhookPayload,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Retell webhook endpoint that does not require EfficientAI API key.

    Organization is inferred via the Retell agent_id mapped to our Agent.voice_ai_agent_id.
    """
    call_payload = payload.call or payload.call_data
    if not call_payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="call payload is required",
        )

    retell_agent_id = payload.agent_id or call_payload.get("agent_id")
    if not retell_agent_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="agent_id is required in payload",
        )

    agent = (
        db.query(Agent)
        .filter(Agent.voice_ai_agent_id == retell_agent_id)
        .first()
    )
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found for provided retell agent_id",
        )

    provider_platform = "retell"
    provider_call_id = payload.provider_call_id
    if not provider_call_id:
        provider_call_id = call_payload.get("call_id") or call_payload.get("id")
    if not provider_call_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="provider_call_id (or call.call_id) is required",
        )

    call_data_payload = dict(payload.call_data or call_payload or {})
    agent_ref_raw = retell_agent_id
    call_event = call_data_payload.get("_event") or payload.event

    return _upsert_call_recording(
        db=db,
        organization_id=agent.organization_id,
        provider_platform=provider_platform,
        provider_call_id=provider_call_id,
        call_data_payload=call_data_payload,
        agent_ref_raw=agent_ref_raw,
        explicit_agent_id=agent.id,
        call_event=call_event,
        source=CallRecordingSource.WEBHOOK,
    )


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

