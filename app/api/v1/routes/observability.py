"""Observability routes for external call ingestion and retrieval."""

import random
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List, Optional, Union
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.dependencies import get_api_key, get_db, get_organization_id, get_workspace_id
from app.services.billing.flexprice_service import (
    record_observability_call_ingested,
    record_observability_call_evaluated,
)
from app.services.observability.call_ingest import (
    OBSERVABILITY_CALL_SOURCES,
    upsert_call_recording,
    upsert_live_event_call_recording,
)
from app.models.database import (
    Agent, APIKey, CallRecording, CallRecordingSource, Integration, IntegrationPlatform,
    CallRecordingStatus,
    Evaluator, EvaluatorResult, EvaluatorResultStatus, Scenario, Workspace,
    ObservabilityLiveEventDedup,
    ObservabilityLiveSloBreach,
)
from app.core.encryption import decrypt_api_key
from app.services.voice_providers import get_voice_provider
from app.services.observability.elevenlabs_trace import (
    enrich_with_turn_metrics,
    extract_trace_id,
    normalize_elevenlabs_otlp,
)
from app.services.observability.provider_call_enrichment import (
    is_sparse_provider_call_data,
    resolve_observability_provider_platform,
)
from app.services.observability.recording_archive import archive_observability_recording_to_s3
from app.services.observability.retell_trace import build_retell_synthetic_trace
from app.services.observability.trace_archive import (
    load_provider_trace,
    persist_provider_trace,
)
from app.services.observability.vapi_trace import build_vapi_synthetic_trace
from app.services.observability.live_ingest import StaleLiveEventError, parse_live_event_ts
from app.services.observability.live_latency import (
    query_live_latency_metrics,
    record_live_latency_samples,
)
from app.services.observability.live_slo import evaluate_llm_p90_slo
from app.services.observability.live_trace import build_live_synthetic_trace
from app.workers.celery_app import process_evaluator_result_task

router = APIRouter(prefix="/observability", tags=["observability"])

_LIVE_SYNTHETIC_PLATFORMS = frozenset({"pipecat", "livekit", "external"})


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
    trace_id: Optional[str] = None

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


class LiveEventEnvelope(BaseModel):
    """Platform-neutral incremental live event envelope."""

    event_id: str = Field(..., min_length=3, max_length=128)
    call_id: str = Field(..., min_length=1, max_length=255)
    event_type: str = Field(..., min_length=3, max_length=64)
    seq: Optional[int] = Field(default=None, ge=0)
    event_ts: str
    platform: str = Field(..., min_length=2, max_length=64)
    agent_ref: Optional[str] = Field(default=None, max_length=128)
    payload: Dict[str, Any] = Field(default_factory=dict)
    trace_id: Optional[str] = Field(default=None, max_length=64)

    model_config = ConfigDict(extra="allow")


def _ensure_live_ingest_enabled() -> None:
    if not settings.OBSERVABILITY_LIVE_INGEST_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Live ingest is disabled for this deployment",
        )


def _ensure_live_aggregates_enabled() -> None:
    if not settings.OBSERVABILITY_LIVE_AGGREGATES_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Live aggregates are disabled for this deployment",
        )


def _validate_live_event_ts_drift(event_ts: datetime) -> None:
    max_drift = max(0, int(settings.OBSERVABILITY_LIVE_EVENT_MAX_TS_DRIFT_SECONDS))
    now = datetime.now(UTC)
    if abs((now - event_ts).total_seconds()) > max_drift:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "event_ts drift exceeds accepted window. "
                f"max={max_drift}s"
            ),
        )


def _cleanup_expired_live_dedup_rows(db: Session, organization_id: UUID) -> None:
    db.query(ObservabilityLiveEventDedup).filter(
        ObservabilityLiveEventDedup.organization_id == organization_id,
        ObservabilityLiveEventDedup.expires_at < datetime.now(UTC),
    ).delete(synchronize_session=False)
    db.flush()


def _issue_efficientai_trace_id() -> str:
    return uuid4().hex


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
        "status": call_recording.status.value if call_recording.status else None,
        "call_event": call_event,
        "is_live": call_event in live_events,
        "direction": call_data.get("direction"),
        "source": call_recording.source.value if call_recording.source else None,
        "provider_platform": call_recording.provider_platform,
        "provider_call_id": call_recording.provider_call_id,
        "trace_id": call_recording.trace_id,
        "last_live_event_ts": call_data.get("_live_last_event_ts"),
        "evaluator_result_id": (
            str(call_recording.evaluator_result_id) if call_recording.evaluator_result_id else None
        ),
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


def _resolve_agent_id_from_ref(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    agent_ref_raw: Optional[str],
) -> Optional[UUID]:
    if not agent_ref_raw:
        return None
    try:
        return UUID(str(agent_ref_raw))
    except ValueError:
        pass
    linked_agent = (
        db.query(Agent)
        .filter(
            Agent.organization_id == organization_id,
            Agent.workspace_id == workspace_id,
            Agent.voice_ai_agent_id == str(agent_ref_raw),
        )
        .first()
    )
    return linked_agent.id if linked_agent else None


def _upsert_call_recording(
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
    source: CallRecordingSource = CallRecordingSource.WEBHOOK,
    trigger_auto_evaluate: bool = False,
) -> Dict[str, Any]:
    """Create/update a call recording and return the serialized API payload."""
    call_recording, action = upsert_call_recording(
        db=db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        provider_platform=provider_platform,
        provider_call_id=provider_call_id,
        call_data_payload=call_data_payload,
        agent_ref_raw=agent_ref_raw,
        explicit_agent_id=explicit_agent_id,
        call_event=call_event,
        trace_id=trace_id,
        source=source,
    )
    if isinstance(call_recording.call_data, dict):
        _maybe_archive_observability_recording(db, call_recording)
        payload = call_recording.call_data if isinstance(call_recording.call_data, dict) else {}
        platform = (call_recording.provider_platform or "").strip().lower()
        if platform in {"retell", "vapi", "elevenlabs"} and _is_terminal_observability_call(payload):
            if _maybe_persist_provider_trace(
                db,
                call_recording,
                call_data=payload,
                provider_platform=platform,
            ):
                db.commit()
                db.refresh(call_recording)
    _warn_if_trace_quota_exceeded(db, organization_id, call_recording)

    agent_obj = None
    if call_recording.agent_id:
        agent_obj = db.query(Agent).filter(Agent.id == call_recording.agent_id).first()

    response = _serialize_call_recording(call_recording, include_data=True, agent=agent_obj)
    response["action"] = action
    if trigger_auto_evaluate:
        _maybe_auto_evaluate_call_recording(
            db=db,
            organization_id=organization_id,
            workspace_id=workspace_id,
            call_recording=call_recording,
            agent=agent_obj,
        )
    return response


def _warn_if_trace_quota_exceeded(
    db: Session,
    organization_id: UUID,
    call_recording: CallRecording,
) -> None:
    quota = settings.OBSERVABILITY_TRACE_QUOTA_PER_ORG_PER_DAY
    if quota is None or quota <= 0:
        return
    trace_id = call_recording.trace_id
    call_data = call_recording.call_data if isinstance(call_recording.call_data, dict) else {}
    if not trace_id:
        trace_id = call_data.get("trace_id")
    if not trace_id:
        return

    day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    trace_count = (
        db.query(CallRecording)
        .filter(
            CallRecording.organization_id == organization_id,
            CallRecording.created_at >= day_start,
            CallRecording.trace_id.isnot(None),
            CallRecording.source.in_(OBSERVABILITY_CALL_SOURCES),
        )
        .count()
    )
    if trace_count > quota:
        logger.warning(
            "Observability trace quota exceeded for org {}: count={} quota={}",
            organization_id,
            trace_count,
            quota,
        )


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
    db_key.last_used = datetime.now(UTC)
    db.commit()
    return db_key.organization_id


def _process_flat_payload_for_workspace(
    body: Dict[str, Any],
    organization_id: UUID,
    workspace_id: UUID,
    db: Session,
) -> Dict[str, Any]:
    """Process a flat CallIngestionPayload-style body in a specific workspace."""
    payload = CallIngestionPayload.model_validate(body)

    provider_call_id = payload.id
    provider_platform = (payload.provider_platform or "external").lower().strip()

    call_data_payload: Dict[str, Any] = {}
    for field in (
        "startedAt", "endedAt", "to_phone_number", "from_phone_number",
        "messages", "metadata", "endedReason", "recording_url", "trace_id",
    ):
        value = getattr(payload, field, None)
        if value is not None:
            call_data_payload[field] = value

    if payload.model_extra:
        call_data_payload.update(payload.model_extra)

    agent_ref_raw = str(payload.agent_id) if payload.agent_id is not None else None
    explicit_agent_id = _resolve_agent_id_from_ref(
        db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_ref_raw=agent_ref_raw,
    )

    call_event: Optional[str] = None
    if payload.endedAt:
        call_event = "call_ended"
    elif payload.startedAt:
        call_event = "call_started"

    return _upsert_call_recording(
        db=db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        provider_platform=provider_platform,
        provider_call_id=provider_call_id,
        call_data_payload=call_data_payload,
        agent_ref_raw=agent_ref_raw,
        explicit_agent_id=explicit_agent_id,
        call_event=call_event,
        trace_id=payload.trace_id or call_data_payload.get("trace_id"),
        source=CallRecordingSource.WEBHOOK,
        trigger_auto_evaluate=True,
    )


def _process_flat_payload(body: Dict[str, Any], organization_id: UUID, db: Session) -> Dict[str, Any]:
    """Process a flat CallIngestionPayload-style body in the org's default workspace."""
    workspace_id = _resolve_default_workspace_id(db, organization_id)
    return _process_flat_payload_for_workspace(body, organization_id, workspace_id, db)


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
    explicit_agent_id = _resolve_agent_id_from_ref(
        db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_ref_raw=str(agent_ref_raw) if agent_ref_raw else None,
    )

    return _upsert_call_recording(
        db=db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        provider_platform=provider_platform,
        provider_call_id=provider_call_id,
        call_data_payload=call_data_payload,
        agent_ref_raw=str(agent_ref_raw) if agent_ref_raw else None,
        explicit_agent_id=explicit_agent_id,
        call_event=call_event,
        trace_id=body.get("trace_id") or call_data_payload.get("trace_id"),
        source=CallRecordingSource.WEBHOOK,
        trigger_auto_evaluate=True,
    )


def _process_named_provider_payload(
    body: Dict[str, Any],
    organization_id: UUID,
    db: Session,
    provider_platform: str,
) -> Dict[str, Any]:
    normalized = dict(body)
    normalized["provider_platform"] = provider_platform
    if "call" not in normalized and "call_data" not in normalized:
        if "call_id" in normalized or "id" in normalized:
            normalized["call"] = dict(normalized)
    if "event" not in normalized:
        status_value = normalized.get("status") or normalized.get("call_status")
        if status_value:
            normalized["event"] = str(status_value)
    return _process_provider_payload(normalized, organization_id, db)


def _refresh_call_data_from_provider(
    *,
    db: Session,
    organization_id: UUID,
    call_recording: CallRecording,
) -> Dict[str, Any]:
    """Fetch latest provider call payload for an existing call recording."""
    provider_call_id = call_recording.provider_call_id
    provider_platform = (call_recording.provider_platform or "").strip().lower()
    if not provider_platform or provider_platform == "external":
        provider_platform = resolve_observability_provider_platform(call_recording, db=db)
        if provider_platform and provider_platform != "external":
            call_recording.provider_platform = provider_platform
            db.commit()
            db.refresh(call_recording)
    if not provider_call_id or not provider_platform or provider_platform == "external":
        raise ValueError("Call does not have provider information")
    if not call_recording.agent_id:
        raise ValueError("Call is not linked to an internal agent")

    agent = (
        db.query(Agent)
        .filter(
            Agent.id == call_recording.agent_id,
            Agent.organization_id == organization_id,
            Agent.workspace_id == call_recording.workspace_id,
        )
        .first()
    )
    if not agent or not agent.voice_ai_integration_id:
        raise ValueError("Agent or voice integration not found")

    integration = (
        db.query(Integration)
        .filter(
            Integration.id == agent.voice_ai_integration_id,
            Integration.organization_id == organization_id,
            Integration.is_active == True,
        )
        .first()
    )
    if not integration:
        raise ValueError("Integration not found")

    decrypted_api_key = decrypt_api_key(integration.api_key)
    provider_class = get_voice_provider(provider_platform)
    provider_kwargs: Dict[str, Any] = {"api_key": decrypted_api_key}
    if provider_platform == IntegrationPlatform.VAPI.value and integration.public_key:
        provider_kwargs["public_key"] = integration.public_key
    provider = provider_class(**provider_kwargs)
    refreshed_call_data = provider.retrieve_call_metrics(str(provider_call_id))
    if not isinstance(refreshed_call_data, dict) or not refreshed_call_data:
        raise ValueError("Provider returned empty call metrics payload")
    return refreshed_call_data


def _resolve_provider_api_key_for_call(
    db: Session,
    organization_id: UUID,
    call_recording: CallRecording,
) -> Optional[str]:
    if not call_recording.agent_id:
        return None
    agent = (
        db.query(Agent)
        .filter(
            Agent.id == call_recording.agent_id,
            Agent.organization_id == organization_id,
            Agent.workspace_id == call_recording.workspace_id,
        )
        .first()
    )
    if not agent or not agent.voice_ai_integration_id:
        return None
    integration = (
        db.query(Integration)
        .filter(
            Integration.id == agent.voice_ai_integration_id,
            Integration.organization_id == organization_id,
            Integration.is_active == True,
        )
        .first()
    )
    if not integration or not integration.api_key:
        return None
    return decrypt_api_key(integration.api_key)


def _is_terminal_observability_call(call_data: Dict[str, Any]) -> bool:
    status_name = str(
        call_data.get("call_status")
        or call_data.get("status")
        or ""
    ).lower().strip()
    return bool(
        status_name in {"ended", "completed", "done", "failed", "call_ended"}
        or call_data.get("endedAt")
        or call_data.get("ended_at")
        or call_data.get("end_timestamp")
        or call_data.get("endedReason")
        or call_data.get("ended_reason")
        or call_data.get("disconnection_reason")
    )


def _maybe_archive_observability_recording(
    db: Session,
    call_recording: CallRecording,
    call_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = call_data if isinstance(call_data, dict) else (
        call_recording.call_data if isinstance(call_recording.call_data, dict) else {}
    )
    if not payload or not _is_terminal_observability_call(payload):
        return payload

    provider_platform = (call_recording.provider_platform or payload.get("provider_platform") or "").strip().lower()
    if not provider_platform:
        return payload

    provider_api_key = _resolve_provider_api_key_for_call(
        db=db,
        organization_id=call_recording.organization_id,
        call_recording=call_recording,
    )
    archived = archive_observability_recording_to_s3(
        call_data=payload,
        provider_platform=provider_platform,
        organization_id=call_recording.organization_id,
        call_short_id=call_recording.call_short_id,
        provider_api_key=provider_api_key,
    )
    if archived.get("recording_s3_key") and archived.get("recording_s3_key") != payload.get("recording_s3_key"):
        call_recording.call_data = archived
        call_recording.status = CallRecordingStatus.UPDATED
        db.commit()
        db.refresh(call_recording)
    return archived


def _maybe_enrich_sparse_provider_call(
    db: Session,
    organization_id: UUID,
    call_recording: CallRecording,
) -> CallRecording:
    """Pull full provider metrics when a hosted call row only has webhook-lite data."""
    call_data = call_recording.call_data if isinstance(call_recording.call_data, dict) else {}
    if not call_data or not call_recording.provider_call_id or not call_recording.agent_id:
        return call_recording

    provider_platform = resolve_observability_provider_platform(call_recording, call_data, db=db)
    if provider_platform in {"", "external"}:
        return call_recording
    if provider_platform != (call_recording.provider_platform or "").strip().lower():
        call_recording.provider_platform = provider_platform

    if not _is_terminal_observability_call(call_data):
        if call_recording.provider_platform != provider_platform:
            db.commit()
            db.refresh(call_recording)
        return call_recording

    if not is_sparse_provider_call_data(call_data, provider_platform):
        if call_recording.provider_platform != provider_platform:
            db.commit()
            db.refresh(call_recording)
        return call_recording

    try:
        refreshed = _refresh_call_data_from_provider(
            db=db,
            organization_id=organization_id,
            call_recording=call_recording,
        )
        call_recording.call_data = refreshed
        call_recording.status = CallRecordingStatus.UPDATED
        _maybe_archive_observability_recording(db, call_recording, refreshed)
        _maybe_persist_provider_trace(
            db,
            call_recording,
            call_data=refreshed,
            provider_platform=provider_platform,
        )
        db.commit()
        db.refresh(call_recording)
    except Exception as exc:
        logger.warning(
            "Sparse provider call enrichment failed for call_short_id={}: {}",
            call_recording.call_short_id,
            exc,
        )
        db.rollback()
    return call_recording


def _prepare_observability_call_recording(
    db: Session,
    organization_id: UUID,
    call_recording: CallRecording,
    *,
    enrich: bool = True,
) -> CallRecording:
    """Load sharded call payloads and optionally pull full provider metrics."""
    from app.services.live_entity_storage import hydrate_call_recordings

    hydrate_call_recordings([call_recording])
    if enrich:
        call_recording = _maybe_enrich_sparse_provider_call(db, organization_id, call_recording)
    return call_recording


def _resolve_elevenlabs_integration_for_call(
    *,
    db: Session,
    organization_id: UUID,
    workspace_id: UUID,
    call_recording: CallRecording,
    call_data: Dict[str, Any],
) -> Optional[Integration]:
    integration_id = call_data.get("integration_id")
    if integration_id:
        try:
            parsed = UUID(str(integration_id))
            row = db.query(Integration).filter(
                Integration.id == parsed,
                Integration.organization_id == organization_id,
                Integration.is_active == True,
            ).first()
            row_platform = row.platform.value if (row and hasattr(row.platform, "value")) else str(getattr(row, "platform", "")).lower()
            if row and row_platform == IntegrationPlatform.ELEVENLABS.value:
                return row
        except Exception:
            pass

    if call_recording.agent_id:
        agent = db.query(Agent).filter(
            Agent.id == call_recording.agent_id,
            Agent.organization_id == organization_id,
            Agent.workspace_id == workspace_id,
        ).first()
        if agent and agent.voice_ai_integration_id:
            row = db.query(Integration).filter(
                Integration.id == agent.voice_ai_integration_id,
                Integration.organization_id == organization_id,
                Integration.is_active == True,
            ).first()
            row_platform = row.platform.value if (row and hasattr(row.platform, "value")) else str(getattr(row, "platform", "")).lower()
            if row and row_platform == IntegrationPlatform.ELEVENLABS.value:
                return row

    provider_agent_id = call_data.get("agent_id")
    if provider_agent_id:
        agent = db.query(Agent).filter(
            Agent.organization_id == organization_id,
            Agent.workspace_id == workspace_id,
            Agent.voice_ai_agent_id == str(provider_agent_id),
        ).first()
        if agent and agent.voice_ai_integration_id:
            row = db.query(Integration).filter(
                Integration.id == agent.voice_ai_integration_id,
                Integration.organization_id == organization_id,
                Integration.is_active == True,
            ).first()
            row_platform = row.platform.value if (row and hasattr(row.platform, "value")) else str(getattr(row, "platform", "")).lower()
            if row and row_platform == IntegrationPlatform.ELEVENLABS.value:
                return row

    return None


def _build_elevenlabs_trace_from_stored_data(
    call_data: Dict[str, Any],
    provider_call_id: str,
) -> Optional[Dict[str, Any]]:
    stored_trace = load_provider_trace(call_data)
    if stored_trace:
        return stored_trace

    provider_trace = call_data.get("provider_trace")
    if not isinstance(provider_trace, dict):
        return None
    otlp_payload = provider_trace.get("otlp_traces")
    if not isinstance(otlp_payload, dict):
        return None

    normalized = normalize_elevenlabs_otlp(
        otlp_payload,
        conversation_id=provider_call_id,
        fallback_trace_id=provider_trace.get("trace_id"),
    )
    transcript = call_data.get("transcript")
    if isinstance(transcript, list):
        normalized = enrich_with_turn_metrics(normalized, transcript)
    return normalized


def _maybe_persist_provider_trace(
    db: Session,
    call_recording: CallRecording,
    *,
    call_data: Optional[Dict[str, Any]] = None,
    provider_platform: Optional[str] = None,
    source: Optional[str] = None,
    raw_payload: Optional[Dict[str, Any]] = None,
) -> bool:
    payload = call_data if isinstance(call_data, dict) else (
        call_recording.call_data if isinstance(call_recording.call_data, dict) else {}
    )
    if not payload:
        return False

    platform = (provider_platform or call_recording.provider_platform or "").strip().lower()
    if not platform:
        return False

    existing_provider_trace = payload.get("provider_trace") if isinstance(payload.get("provider_trace"), dict) else {}
    existing_source = existing_provider_trace.get("source") if isinstance(existing_provider_trace, dict) else None
    explicit_trace_id = payload.get("trace_id") or call_recording.trace_id

    trace_payload: Optional[Dict[str, Any]] = None
    if platform == "vapi":
        trace_payload = build_vapi_synthetic_trace(
            payload,
            provider_call_id=str(call_recording.provider_call_id or payload.get("id") or call_recording.call_short_id),
        )
    elif platform == "retell":
        trace_payload = build_retell_synthetic_trace(
            payload,
            provider_call_id=str(
                call_recording.provider_call_id or payload.get("call_id") or call_recording.call_short_id
            ),
        )
    elif platform == "elevenlabs":
        provider_call_id = str(
            call_recording.provider_call_id
            or payload.get("conversation_id")
            or payload.get("call_id")
            or call_recording.call_short_id
        )
        trace_payload = _build_elevenlabs_trace_from_stored_data(payload, provider_call_id)
        if raw_payload is None:
            provider_trace = payload.get("provider_trace")
            if isinstance(provider_trace, dict) and isinstance(provider_trace.get("otlp_traces"), dict):
                raw_payload = provider_trace.get("otlp_traces")
    elif platform in _LIVE_SYNTHETIC_PLATFORMS or isinstance(payload.get("live_transcript"), list):
        trace_payload = build_live_synthetic_trace(
            payload,
            provider_call_id=str(
                call_recording.provider_call_id or payload.get("id") or call_recording.call_short_id
            ),
            provider_platform=platform or "external",
            trace_id=str(explicit_trace_id) if explicit_trace_id else None,
        )

    if not trace_payload:
        return False

    trace_source = source or str(existing_source or trace_payload.get("trace_source") or f"{platform}_synthetic")
    updated = persist_provider_trace(
        call_data=payload,
        provider_platform=platform,
        organization_id=call_recording.organization_id,
        call_short_id=call_recording.call_short_id,
        trace_payload=trace_payload,
        source=trace_source,
        raw_payload=raw_payload if isinstance(raw_payload, dict) else None,
    )
    call_recording.call_data = updated
    trace_id = explicit_trace_id or trace_payload.get("trace_id") or updated.get("trace_id")
    if explicit_trace_id:
        updated["trace_id"] = explicit_trace_id
    if trace_id:
        call_recording.trace_id = str(trace_id)
    call_recording.status = CallRecordingStatus.UPDATED
    db.flush()
    return True


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
    normalized = dict(body)
    event_value = str(normalized.get("event") or "").lower().strip()
    if event_value in {"call_ended", "call_analyzed", "call_completed", "end_of_call_report", "end-of-call-report", "completed"}:
        normalized["event"] = "call_ended"

    response = _process_named_provider_payload(normalized, organization_id, db, "retell")
    call_data = response.get("call_data") if isinstance(response, dict) else None
    call_short_id = response.get("call_short_id") if isinstance(response, dict) else None

    def _is_terminal(payload: Dict[str, Any]) -> bool:
        status_name = str(payload.get("call_status") or payload.get("status") or "").lower().strip()
        return bool(
            status_name in {"ended", "completed", "failed", "call_ended"}
            or payload.get("end_timestamp")
            or payload.get("endedAt")
            or payload.get("disconnection_reason")
        )

    def _is_incomplete(payload: Dict[str, Any]) -> bool:
        has_transcript = bool(
            (isinstance(payload.get("transcript_object"), list) and len(payload.get("transcript_object")) > 0)
            or (isinstance(payload.get("messages"), list) and len(payload.get("messages")) > 0)
            or (isinstance(payload.get("transcript"), str) and payload.get("transcript").strip())
        )
        has_analysis = isinstance(payload.get("call_analysis"), dict) and len(payload.get("call_analysis")) > 0
        has_cost = isinstance(payload.get("call_cost"), dict) and len(payload.get("call_cost")) > 0
        return not (has_transcript and has_analysis and has_cost)

    if isinstance(call_data, dict) and call_short_id and _is_terminal(call_data):
        row = (
            db.query(CallRecording)
            .filter(
                CallRecording.call_short_id == call_short_id,
                CallRecording.organization_id == organization_id,
                CallRecording.source.in_(OBSERVABILITY_CALL_SOURCES),
            )
            .first()
        )
        if row:
            should_refresh = _is_incomplete(call_data) or is_sparse_provider_call_data(call_data, "retell")
            if should_refresh:
                try:
                    refreshed = _refresh_call_data_from_provider(
                        db=db,
                        organization_id=organization_id,
                        call_recording=row,
                    )
                    row.call_data = refreshed
                    row.status = CallRecordingStatus.UPDATED
                    _maybe_archive_observability_recording(db, row, refreshed)
                    _maybe_persist_provider_trace(
                        db,
                        row,
                        call_data=refreshed,
                        provider_platform="retell",
                    )
                    db.commit()
                    db.refresh(row)
                    agent = db.query(Agent).filter(Agent.id == row.agent_id).first() if row.agent_id else None
                    response = _serialize_call_recording(row, include_data=True, agent=agent)
                except Exception as exc:
                    logger.warning(f"[RetellWebhook] Pull fallback refresh failed for {call_short_id}: {exc}")

    return response


@router.post("/calls/webhook/elevenlabs/{api_key}", status_code=status.HTTP_201_CREATED)
async def ingest_elevenlabs_webhook(
    api_key: str,
    body: Dict[str, Any],
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    organization_id = _validate_webhook_api_key(api_key, db)
    if body.get("type") == "post_call_transcription_otel" and isinstance(body.get("data"), dict):
        data = body["data"]
        conversation_id = data.get("conversation_id")
        otlp_payload = data.get("otlp_traces")
        if conversation_id and isinstance(otlp_payload, dict):
            workspace_id = _resolve_default_workspace_id(db, organization_id)
            provider_agent_id = data.get("agent_id")
            integration_id = None
            internal_agent_id = None
            if provider_agent_id:
                linked_agent = db.query(Agent).filter(
                    Agent.organization_id == organization_id,
                    Agent.workspace_id == workspace_id,
                    Agent.voice_ai_agent_id == str(provider_agent_id),
                ).first()
                if linked_agent:
                    internal_agent_id = str(linked_agent.id)
                    if linked_agent.voice_ai_integration_id:
                        integration_id = str(linked_agent.voice_ai_integration_id)

            extracted_trace_id = extract_trace_id(otlp_payload)
            normalized_trace = normalize_elevenlabs_otlp(
                otlp_payload,
                conversation_id=str(conversation_id),
                fallback_trace_id=extracted_trace_id,
            )
            transcript_payload = data.get("transcript")
            if isinstance(transcript_payload, list):
                normalized_trace = enrich_with_turn_metrics(normalized_trace, transcript_payload)
            call_data_payload: Dict[str, Any] = {
                "id": conversation_id,
                "call_id": conversation_id,
                "agent_id": provider_agent_id,
                "provider_platform": "elevenlabs",
                "status": data.get("status") or "done",
                "transcript": transcript_payload,
                "conversation_id": conversation_id,
            }
            call_data_payload = persist_provider_trace(
                call_data=call_data_payload,
                provider_platform="elevenlabs",
                organization_id=organization_id,
                call_short_id=f"el-{str(conversation_id)[:24]}",
                trace_payload=normalized_trace,
                source="elevenlabs_post_call_webhook",
                raw_payload=otlp_payload,
            )
            extracted_trace_id = call_data_payload.get("trace_id") or extracted_trace_id
            if integration_id:
                call_data_payload["integration_id"] = integration_id

            # Reconcile against a previously-created pending call row (e.g. playground
            # web call bootstrapped before ElevenLabs conversation_id was known).
            if internal_agent_id:
                try:
                    internal_agent_uuid = UUID(str(internal_agent_id))
                    pending_row = (
                        db.query(CallRecording)
                        .filter(
                            CallRecording.organization_id == organization_id,
                            CallRecording.workspace_id == workspace_id,
                            CallRecording.provider_platform == "elevenlabs",
                            CallRecording.provider_call_id.is_(None),
                            CallRecording.agent_id == internal_agent_uuid,
                        )
                        .order_by(CallRecording.created_at.desc())
                        .first()
                    )
                    if pending_row:
                        pending_row.provider_call_id = conversation_id
                        pending_row.call_data = call_data_payload
                        pending_row.call_event = "call_ended"
                        pending_row.status = CallRecordingStatus.UPDATED
                        pending_row.source = CallRecordingSource.WEBHOOK
                        if extracted_trace_id:
                            pending_row.trace_id = extracted_trace_id
                        _maybe_persist_provider_trace(
                            db,
                            pending_row,
                            call_data=call_data_payload,
                            provider_platform="elevenlabs",
                            source="elevenlabs_post_call_webhook",
                            raw_payload=otlp_payload,
                        )
                        db.commit()
                        db.refresh(pending_row)
                        agent_obj = db.query(Agent).filter(Agent.id == pending_row.agent_id).first()
                        response = _serialize_call_recording(
                            pending_row,
                            include_data=True,
                            agent=agent_obj,
                        )
                        response["action"] = "updated"
                        _maybe_auto_evaluate_call_recording(
                            db=db,
                            organization_id=organization_id,
                            workspace_id=workspace_id,
                            call_recording=pending_row,
                            agent=agent_obj,
                        )
                        return response
                except Exception:
                    db.rollback()

            return _process_provider_payload(
                {
                    "provider_platform": "elevenlabs",
                    "provider_call_id": conversation_id,
                    "event": "call_ended",
                    "trace_id": extracted_trace_id,
                    "agent_id": internal_agent_id or provider_agent_id,
                    "call": call_data_payload,
                },
                organization_id,
                db,
            )
    return _process_named_provider_payload(body, organization_id, db, "elevenlabs")


@router.post("/calls/webhook/vapi/{api_key}", status_code=status.HTTP_201_CREATED)
async def ingest_vapi_webhook(
    api_key: str,
    body: Dict[str, Any],
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    organization_id = _validate_webhook_api_key(api_key, db)
    normalized = dict(body)
    status_value = str(
        normalized.get("status")
        or normalized.get("call_status")
        or (normalized.get("call") or {}).get("status")
        or "",
    ).lower().strip()
    if status_value in {"ended", "completed", "end-of-call-report", "done", "failed"}:
        normalized["event"] = "call_ended"

    response = _process_named_provider_payload(normalized, organization_id, db, "vapi")
    call_data = response.get("call_data") if isinstance(response, dict) else None
    call_short_id = response.get("call_short_id") if isinstance(response, dict) else None

    def _is_terminal(payload: Dict[str, Any]) -> bool:
        status_name = str(payload.get("status") or payload.get("call_status") or "").lower().strip()
        return bool(
            status_name in {"ended", "completed", "end-of-call-report", "done", "failed"}
            or payload.get("endedAt")
            or payload.get("ended_at")
            or payload.get("endedReason")
            or payload.get("ended_reason")
        )

    def _is_incomplete(payload: Dict[str, Any]) -> bool:
        has_messages = bool(
            (isinstance(payload.get("messages"), list) and len(payload.get("messages")) > 0)
            or (
                isinstance(payload.get("artifact"), dict)
                and isinstance(payload.get("artifact", {}).get("messages"), list)
                and len(payload.get("artifact", {}).get("messages")) > 0
            )
        )
        has_analysis = isinstance(payload.get("analysis"), dict) and len(payload.get("analysis")) > 0
        has_cost = bool(
            payload.get("cost") is not None
            or (
                isinstance(payload.get("costBreakdown"), dict)
                and len(payload.get("costBreakdown")) > 0
            )
            or (
                isinstance(payload.get("cost_breakdown"), dict)
                and len(payload.get("cost_breakdown")) > 0
            )
        )
        return not (has_messages and has_analysis and has_cost)

    if isinstance(call_data, dict) and call_short_id and _is_terminal(call_data) and _is_incomplete(call_data):
        row = (
            db.query(CallRecording)
            .filter(
                CallRecording.call_short_id == call_short_id,
                CallRecording.organization_id == organization_id,
                CallRecording.source.in_(OBSERVABILITY_CALL_SOURCES),
            )
            .first()
        )
        if row:
            try:
                refreshed = _refresh_call_data_from_provider(
                    db=db,
                    organization_id=organization_id,
                    call_recording=row,
                )
                row.call_data = refreshed
                row.status = CallRecordingStatus.UPDATED
                _maybe_archive_observability_recording(db, row, refreshed)
                _maybe_persist_provider_trace(
                    db,
                    row,
                    call_data=refreshed,
                    provider_platform="vapi",
                )
                db.commit()
                db.refresh(row)
                agent = db.query(Agent).filter(Agent.id == row.agent_id).first() if row.agent_id else None
                response = _serialize_call_recording(row, include_data=True, agent=agent)
            except Exception as exc:
                logger.warning(f"[VapiWebhook] Pull fallback refresh failed for {call_short_id}: {exc}")

    return response


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


@router.post("/observe", status_code=status.HTTP_201_CREATED)
async def observe_call(
    body: Dict[str, Any],
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Header-auth flat call ingest endpoint for SDK observation."""
    del api_key
    return _process_flat_payload_for_workspace(body, organization_id, workspace_id, db)


@router.post("/live/events", status_code=status.HTTP_202_ACCEPTED)
async def ingest_live_event(
    body: Dict[str, Any],
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Ingest an incremental live event with idempotent merge semantics."""
    del api_key
    _ensure_live_ingest_enabled()
    envelope = LiveEventEnvelope.model_validate(body)

    try:
        event_ts_dt = parse_live_event_ts(envelope.event_ts)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    _validate_live_event_ts_drift(event_ts_dt)

    provider_platform = envelope.platform.strip().lower()
    provider_call_id = envelope.call_id.strip()
    trace_id = envelope.trace_id or _issue_efficientai_trace_id()
    now = datetime.now(UTC)

    _cleanup_expired_live_dedup_rows(db, organization_id)
    duplicate_row = (
        db.query(ObservabilityLiveEventDedup)
        .filter(
            ObservabilityLiveEventDedup.organization_id == organization_id,
            ObservabilityLiveEventDedup.event_id == envelope.event_id,
            ObservabilityLiveEventDedup.expires_at >= now,
        )
        .first()
    )
    if duplicate_row:
        duplicate_trace_id = envelope.trace_id
        if not duplicate_trace_id and duplicate_row.call_short_id:
            existing_call = (
                db.query(CallRecording)
                .filter(
                    CallRecording.call_short_id == duplicate_row.call_short_id,
                    CallRecording.organization_id == organization_id,
                )
                .first()
            )
            if existing_call:
                existing_payload = existing_call.call_data if isinstance(existing_call.call_data, dict) else {}
                duplicate_trace_id = existing_call.trace_id or existing_payload.get("trace_id")
        return {
            "accepted": True,
            "duplicate": True,
            "event_id": envelope.event_id,
            "trace_id": duplicate_trace_id,
            "call_short_id": duplicate_row.call_short_id,
        }

    live_event = envelope.model_dump()
    live_event["platform"] = provider_platform
    live_event["event_ts"] = event_ts_dt.isoformat()
    live_event["trace_id"] = trace_id
    explicit_agent_id = _resolve_agent_id_from_ref(
        db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_ref_raw=envelope.agent_ref,
    )

    try:
        call_recording, action = upsert_live_event_call_recording(
            db=db,
            organization_id=organization_id,
            workspace_id=workspace_id,
            provider_platform=provider_platform,
            provider_call_id=provider_call_id,
            live_event=live_event,
            max_out_of_order_seq=settings.OBSERVABILITY_LIVE_EVENT_MAX_OUT_OF_ORDER_SEQ,
            agent_ref_raw=envelope.agent_ref,
            explicit_agent_id=explicit_agent_id,
            source=CallRecordingSource.WEBHOOK,
            persist=False,
        )
    except StaleLiveEventError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    dedup_ttl = max(60, int(settings.OBSERVABILITY_LIVE_EVENT_IDEMPOTENCY_TTL_SECONDS))
    db.add(
        ObservabilityLiveEventDedup(
            organization_id=organization_id,
            workspace_id=workspace_id,
            event_id=envelope.event_id,
            provider_platform=provider_platform,
            provider_call_id=provider_call_id,
            call_short_id=call_recording.call_short_id,
            seq=envelope.seq,
            event_ts=event_ts_dt,
            expires_at=now + timedelta(seconds=dedup_ttl),
        )
    )

    latency_samples_written = 0
    if settings.OBSERVABILITY_LIVE_AGGREGATES_ENABLED:
        latency_samples_written = record_live_latency_samples(
            db=db,
            organization_id=organization_id,
            workspace_id=workspace_id,
            call_recording=call_recording,
            provider_platform=provider_platform,
            provider_call_id=provider_call_id,
            event_payload=envelope.payload,
            event_ts=event_ts_dt,
        )

    slo_breach = None
    if settings.OBSERVABILITY_LIVE_AGGREGATES_ENABLED and settings.OBSERVABILITY_LIVE_SLO_ALERTS_ENABLED:
        slo_breach = evaluate_llm_p90_slo(
            db=db,
            organization_id=organization_id,
            workspace_id=workspace_id,
            call_recording=call_recording,
            provider_platform=provider_platform,
        )

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return {
            "accepted": True,
            "duplicate": True,
            "event_id": envelope.event_id,
            "trace_id": trace_id,
            "call_short_id": call_recording.call_short_id,
        }

    if action == "created":
        record_observability_call_ingested(
            organization_id,
            call_recording.call_short_id,
            workspace_id=workspace_id,
            provider=provider_platform,
        )

    if call_recording.call_event in {"call_ended", "call_failed"}:
        db.refresh(call_recording)
        if _maybe_persist_provider_trace(
            db,
            call_recording,
            call_data=call_recording.call_data if isinstance(call_recording.call_data, dict) else {},
            provider_platform=provider_platform,
        ):
            db.commit()
            db.refresh(call_recording)

    evaluator_hook_queued = False
    if (
        settings.OBSERVABILITY_LIVE_SLO_AUTOMATION_ENABLED
        and slo_breach is not None
        and call_recording.call_event in {"call_ended", "call_failed"}
    ):
        try:
            _maybe_auto_evaluate_call_recording(
                db=db,
                organization_id=organization_id,
                workspace_id=workspace_id,
                call_recording=call_recording,
                agent=None,
            )
            slo_breach.evaluator_queued = True
            db.commit()
            evaluator_hook_queued = True
        except Exception:
            db.rollback()

    return {
        "accepted": True,
        "duplicate": False,
        "action": action,
        "event_id": envelope.event_id,
        "call_short_id": call_recording.call_short_id,
        "provider_platform": provider_platform,
        "provider_call_id": provider_call_id,
        "trace_id": trace_id,
        "latency_samples_written": latency_samples_written,
        "slo_breach_detected": bool(slo_breach),
        "evaluator_hook_queued": evaluator_hook_queued,
    }



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
            CallRecording.source.in_(OBSERVABILITY_CALL_SOURCES),
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


@router.get("/calls/summary", response_model=Dict[str, Any])
async def calls_summary(
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    del api_key
    call_recordings = (
        db.query(CallRecording)
        .filter(
            CallRecording.organization_id == organization_id,
            CallRecording.workspace_id == workspace_id,
            CallRecording.source.in_(OBSERVABILITY_CALL_SOURCES),
        )
        .all()
    )
    total_calls = len(call_recordings)
    trace_linked_calls = 0
    trace_available_calls = 0
    evaluated_calls = 0
    ended_calls = 0
    failed_calls = 0
    started_calls = 0
    other_calls = 0
    for recording in call_recordings:
        call_data = recording.call_data if isinstance(recording.call_data, dict) else {}
        trace_id = recording.trace_id or call_data.get("trace_id")
        if trace_id:
            trace_linked_calls += 1
        provider_trace = call_data.get("provider_trace")
        has_stored_provider_trace = isinstance(provider_trace, dict) and bool(
            provider_trace.get("normalized_trace") or provider_trace.get("otlp_traces") or provider_trace.get("trace_s3_key")
        )
        has_retell_signal = bool(
            (
                isinstance(call_data.get("transcript_object"), list)
                and len(call_data.get("transcript_object")) > 0
            )
            or (
                isinstance(call_data.get("transcript"), str)
                and call_data.get("transcript", "").strip()
            )
            or (
                isinstance(call_data.get("latency"), dict)
                and len(call_data.get("latency")) > 0
            )
        )
        has_vapi_signal = bool(
            (
                isinstance(call_data.get("messages"), list)
                and len(call_data.get("messages")) > 0
            )
            or (
                isinstance(call_data.get("artifact"), dict)
                and isinstance(call_data.get("artifact", {}).get("messages"), list)
                and len(call_data.get("artifact", {}).get("messages")) > 0
            )
            or (
                isinstance(call_data.get("analysis"), dict)
                and len(call_data.get("analysis")) > 0
            )
            or (
                isinstance(call_data.get("artifact"), dict)
                and isinstance(call_data.get("artifact", {}).get("performanceMetrics"), dict)
                and len(call_data.get("artifact", {}).get("performanceMetrics")) > 0
            )
        )
        platform = (recording.provider_platform or "").strip().lower()
        has_synthetic_candidate = (
            platform == "retell" and has_retell_signal
        ) or (
            platform == "vapi" and has_vapi_signal
        )
        if trace_id or has_stored_provider_trace or has_synthetic_candidate:
            trace_available_calls += 1
        if recording.evaluator_result_id:
            evaluated_calls += 1
        event = (recording.call_event or "").strip().lower()
        if event == "call_ended":
            ended_calls += 1
        elif event in {"call_failed", "failed"}:
            failed_calls += 1
        elif event == "call_started":
            started_calls += 1
        elif event:
            other_calls += 1

    duration_seconds = [
        value for value in (_extract_duration_seconds(recording) for recording in call_recordings) if value
    ]
    total_minutes = sum(duration_seconds) / 60.0 if duration_seconds else 0.0
    avg_duration_ms = (sum(duration_seconds) / len(duration_seconds) * 1000.0) if duration_seconds else 0.0
    trace_link_rate = (trace_linked_calls / total_calls * 100.0) if total_calls else 0.0
    trace_available_rate = (trace_available_calls / total_calls * 100.0) if total_calls else 0.0
    evaluated_rate = (evaluated_calls / total_calls * 100.0) if total_calls else 0.0
    return {
        "total_calls": total_calls,
        "total_minutes": round(total_minutes, 2),
        "avg_duration_ms": round(avg_duration_ms, 2),
        "avg_latency_ms": round(avg_duration_ms, 2),
        "trace_linked_calls": trace_linked_calls,
        "trace_link_rate_pct": round(trace_link_rate, 2),
        "trace_available_calls": trace_available_calls,
        "trace_available_rate_pct": round(trace_available_rate, 2),
        "evaluated_calls": evaluated_calls,
        "evaluated_rate_pct": round(evaluated_rate, 2),
        "event_breakdown": {
            "call_ended": ended_calls,
            "call_failed": failed_calls,
            "call_started": started_calls,
            "other": other_calls,
        },
        "live_feature_flags": {
            "live_ingest_enabled": settings.OBSERVABILITY_LIVE_INGEST_ENABLED,
            "live_aggregates_enabled": settings.OBSERVABILITY_LIVE_AGGREGATES_ENABLED,
            "live_dashboard_enabled": settings.OBSERVABILITY_LIVE_DASHBOARD_ENABLED,
        },
    }


@router.get("/live/metrics/latency", response_model=Dict[str, Any])
async def get_live_latency_metrics(
    platform: Optional[str] = None,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Return rolling live latency percentiles across all agents."""
    del api_key
    _ensure_live_aggregates_enabled()
    normalized_platform = platform.strip().lower() if isinstance(platform, str) and platform.strip() else None
    return {
        "scope": "workspace",
        "platform": normalized_platform,
        "windows": {
            "60s": query_live_latency_metrics(
                db=db,
                organization_id=organization_id,
                workspace_id=workspace_id,
                window_seconds=60,
                provider_platform=normalized_platform,
            ),
            "300s": query_live_latency_metrics(
                db=db,
                organization_id=organization_id,
                workspace_id=workspace_id,
                window_seconds=300,
                provider_platform=normalized_platform,
            ),
        },
    }


@router.get("/live/agents/{agent_id}/latency", response_model=Dict[str, Any])
async def get_live_agent_latency_metrics(
    agent_id: str,
    platform: Optional[str] = None,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Return rolling live latency percentiles for a specific agent."""
    del api_key
    _ensure_live_aggregates_enabled()
    try:
        agent_uuid = UUID(agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid agent_id") from exc
    normalized_platform = platform.strip().lower() if isinstance(platform, str) and platform.strip() else None
    return {
        "scope": "agent",
        "agent_id": str(agent_uuid),
        "platform": normalized_platform,
        "windows": {
            "60s": query_live_latency_metrics(
                db=db,
                organization_id=organization_id,
                workspace_id=workspace_id,
                window_seconds=60,
                agent_id=agent_uuid,
                provider_platform=normalized_platform,
            ),
            "300s": query_live_latency_metrics(
                db=db,
                organization_id=organization_id,
                workspace_id=workspace_id,
                window_seconds=300,
                agent_id=agent_uuid,
                provider_platform=normalized_platform,
            ),
        },
    }


@router.get("/live/slo/breaches", response_model=List[Dict[str, Any]])
async def list_live_slo_breaches(
    limit: int = 50,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """List recent live SLO breaches for operational triage."""
    del api_key
    rows = (
        db.query(ObservabilityLiveSloBreach)
        .filter(
            ObservabilityLiveSloBreach.organization_id == organization_id,
            ObservabilityLiveSloBreach.workspace_id == workspace_id,
        )
        .order_by(ObservabilityLiveSloBreach.created_at.desc())
        .limit(max(1, min(limit, 200)))
        .all()
    )
    return [
        {
            "id": str(row.id),
            "call_short_id": row.call_short_id,
            "provider_platform": row.provider_platform,
            "agent_id": str(row.agent_id) if row.agent_id else None,
            "metric_name": row.metric_name,
            "window_seconds": row.window_seconds,
            "p90_ms": row.p90_ms,
            "threshold_ms": row.threshold_ms,
            "sample_count": row.sample_count,
            "evaluator_queued": row.evaluator_queued,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
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
            CallRecording.source.in_(OBSERVABILITY_CALL_SOURCES),
        )
        .first()
    )

    if not call_recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call not found",
        )

    call_recording = _prepare_observability_call_recording(db, organization_id, call_recording)
    call_data = call_recording.call_data if isinstance(call_recording.call_data, dict) else {}
    provider_platform = resolve_observability_provider_platform(call_recording, call_data, db=db)
    if provider_platform == "elevenlabs" and not load_provider_trace(call_data):
        try:
            await _query_elevenlabs_trace_for_call(
                db=db,
                organization_id=organization_id,
                workspace_id=workspace_id,
                call_recording=call_recording,
                call_data=call_data,
            )
            call_data = call_recording.call_data if isinstance(call_recording.call_data, dict) else call_data
        except HTTPException:
            pass

    # region agent log
    from app.utils.debug_agent_log import agent_debug_log

    call_data_dbg = call_data
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


@router.post("/calls/{call_short_id}/refresh", response_model=Dict[str, Any])
async def refresh_observability_call(
    call_short_id: str,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Refresh an observability call by pulling latest metrics from the provider."""
    del api_key

    call_recording = (
        db.query(CallRecording)
        .filter(
            CallRecording.call_short_id == call_short_id,
            CallRecording.organization_id == organization_id,
            CallRecording.workspace_id == workspace_id,
            CallRecording.source.in_(OBSERVABILITY_CALL_SOURCES),
        )
        .first()
    )
    if not call_recording:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")

    try:
        refreshed_call_data = _refresh_call_data_from_provider(
            db=db,
            organization_id=organization_id,
            call_recording=call_recording,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to refresh provider call metrics: {exc}",
        ) from exc

    call_recording.call_data = refreshed_call_data
    call_recording.status = CallRecordingStatus.UPDATED
    _maybe_archive_observability_recording(db, call_recording, refreshed_call_data)
    provider_platform = (call_recording.provider_platform or "").strip().lower()
    if provider_platform == "elevenlabs" and call_recording.provider_call_id:
        integration = _resolve_elevenlabs_integration_for_call(
            db=db,
            organization_id=organization_id,
            workspace_id=workspace_id,
            call_recording=call_recording,
            call_data=refreshed_call_data,
        )
        if integration is not None:
            try:
                decrypted_api_key = decrypt_api_key(integration.api_key)
                provider_class = get_voice_provider("elevenlabs")
                provider = provider_class(api_key=decrypted_api_key)
                provider_trace_payload = provider.retrieve_provider_trace(str(call_recording.provider_call_id))
                otlp_payload = provider_trace_payload.get("otlp_traces")
                if isinstance(otlp_payload, dict):
                    normalized_trace = normalize_elevenlabs_otlp(
                        otlp_payload,
                        conversation_id=str(call_recording.provider_call_id),
                        fallback_trace_id=extract_trace_id(otlp_payload),
                    )
                    transcript = provider_trace_payload.get("transcript")
                    if isinstance(transcript, list):
                        normalized_trace = enrich_with_turn_metrics(normalized_trace, transcript)
                    call_recording.call_data = persist_provider_trace(
                        call_data=call_recording.call_data if isinstance(call_recording.call_data, dict) else {},
                        provider_platform="elevenlabs",
                        organization_id=call_recording.organization_id,
                        call_short_id=call_recording.call_short_id,
                        trace_payload=normalized_trace,
                        source="elevenlabs_refresh_fetch",
                        raw_payload=otlp_payload,
                    )
                    call_recording.trace_id = normalized_trace.get("trace_id") or call_recording.trace_id
            except Exception as exc:
                logger.warning(
                    "ElevenLabs trace refresh fetch failed for call_short_id={}: {}",
                    call_recording.call_short_id,
                    exc,
                )
    else:
        _maybe_persist_provider_trace(
            db,
            call_recording,
            call_data=refreshed_call_data,
            provider_platform=provider_platform,
        )
    db.commit()
    db.refresh(call_recording)

    refreshed_agent = db.query(Agent).filter(Agent.id == call_recording.agent_id).first()
    return _serialize_call_recording(call_recording, include_data=True, agent=refreshed_agent)


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
            CallRecording.source.in_(OBSERVABILITY_CALL_SOURCES),
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
                        CallRecording.source.in_(OBSERVABILITY_CALL_SOURCES),
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


@router.get("/calls/{call_short_id}/live-audio")
async def stream_observability_live_call_audio(
    call_short_id: str,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Return partial merged mono WAV for an in-progress telephony call."""
    from io import BytesIO

    from fastapi.responses import StreamingResponse

    from app.services.telephony.call_recording_lifecycle import LIVE_CALL_EVENTS
    from app.services.telephony.live_recording import merge_live_tracks_mono

    del api_key

    call_recording = (
        db.query(CallRecording)
        .filter(
            CallRecording.call_short_id == call_short_id,
            CallRecording.organization_id == organization_id,
            CallRecording.workspace_id == workspace_id,
            CallRecording.source.in_(OBSERVABILITY_CALL_SOURCES),
        )
        .first()
    )
    if not call_recording:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")

    call_event = (call_recording.call_event or "").lower()
    if call_event not in LIVE_CALL_EVENTS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Live audio is only available while the call is in progress",
        )

    call_data = call_recording.call_data if isinstance(call_recording.call_data, dict) else {}
    user_path = call_data.get("live_user_audio_path")
    bot_path = call_data.get("live_bot_audio_path")
    if not user_path or not bot_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Live recording paths are not registered for this call yet",
        )

    wav_bytes, duration_sec, _sample_rate = merge_live_tracks_mono(str(user_path), str(bot_path))
    if not wav_bytes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No live audio captured yet",
        )

    return StreamingResponse(
        BytesIO(wav_bytes),
        media_type="audio/wav",
        headers={
            "Content-Disposition": f'inline; filename="call_{call_short_id}_live.wav"',
            "Cache-Control": "no-store",
            "X-Audio-Duration-Sec": f"{duration_sec:.3f}",
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
    """Stream call recording audio for observability calls (S3-backed)."""
    from io import BytesIO

    from fastapi.responses import StreamingResponse

    del api_key

    call_recording = (
        db.query(CallRecording)
        .filter(
            CallRecording.call_short_id == call_short_id,
            CallRecording.organization_id == organization_id,
            CallRecording.workspace_id == workspace_id,
            CallRecording.source.in_(OBSERVABILITY_CALL_SOURCES),
        )
        .first()
    )
    if not call_recording:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")

    call_recording = _prepare_observability_call_recording(
        db, organization_id, call_recording, enrich=False
    )
    call_data = call_recording.call_data if isinstance(call_recording.call_data, dict) else {}
    if not call_data.get("recording_s3_key"):
        call_data = _maybe_archive_observability_recording(db, call_recording, call_data)

    s3_key = call_data.get("recording_s3_key")
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
            CallRecording.source.in_(OBSERVABILITY_CALL_SOURCES),
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


def _extract_duration_seconds(call_recording: CallRecording) -> Optional[float]:
    call_data = call_recording.call_data if isinstance(call_recording.call_data, dict) else {}
    return _resolve_call_duration_seconds(call_data)


def _queue_call_evaluation(
    *,
    db: Session,
    organization_id: UUID,
    workspace_id: UUID,
    call_recording: CallRecording,
    evaluator_id: str,
    background_tasks: Optional[BackgroundTasks] = None,
) -> Dict[str, Any]:
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
        evaluator_uuid = UUID(evaluator_id)
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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate unique result ID",
        )

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

    if background_tasks is not None:
        background_tasks.add_task(
            record_observability_call_evaluated,
            organization_id,
            call_recording.call_short_id,
            workspace_id=workspace_id,
        )
    else:
        try:
            record_observability_call_evaluated(
                organization_id,
                call_recording.call_short_id,
                workspace_id=workspace_id,
            )
        except Exception:
            pass

    return {
        "evaluator_result_id": str(evaluator_result.id),
        "result_id": evaluator_result.result_id,
        "status": evaluator_result.status,
        "message": "Evaluation queued successfully",
    }


def _maybe_auto_evaluate_call_recording(
    *,
    db: Session,
    organization_id: UUID,
    workspace_id: UUID,
    call_recording: CallRecording,
    agent: Optional[Agent] = None,
) -> None:
    if call_recording.call_event != "call_ended":
        return
    if call_recording.evaluator_result_id:
        return
    if not call_recording.agent_id:
        return

    agent_obj = agent
    if agent_obj is None:
        agent_obj = (
            db.query(Agent)
            .filter(
                Agent.id == call_recording.agent_id,
                Agent.organization_id == organization_id,
                Agent.workspace_id == workspace_id,
            )
            .first()
        )
    if not agent_obj or not agent_obj.observability_auto_evaluator_id:
        return

    try:
        _queue_call_evaluation(
            db=db,
            organization_id=organization_id,
            workspace_id=workspace_id,
            call_recording=call_recording,
            evaluator_id=str(agent_obj.observability_auto_evaluator_id),
            background_tasks=None,
        )
    except Exception:
        # Best-effort auto-eval should not block webhook ingest.
        return


def _normalize_span_attributes(raw_attrs: Any) -> Dict[str, Any]:
    if isinstance(raw_attrs, dict):
        return raw_attrs
    if isinstance(raw_attrs, list):
        result: Dict[str, Any] = {}
        for item in raw_attrs:
            if not isinstance(item, dict):
                continue
            key = item.get("key")
            if not key:
                continue
            value = item.get("value")
            if isinstance(value, dict) and "stringValue" in value:
                result[key] = value.get("stringValue")
            elif isinstance(value, dict) and "intValue" in value:
                result[key] = value.get("intValue")
            elif isinstance(value, dict) and "doubleValue" in value:
                result[key] = value.get("doubleValue")
            elif isinstance(value, dict) and "boolValue" in value:
                result[key] = value.get("boolValue")
            else:
                result[key] = value
        return result
    return {}


def _to_epoch_ms(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit() or (
            stripped.replace(".", "", 1).isdigit() and stripped.count(".") <= 1
        ):
            return _to_epoch_ms(float(stripped))
        try:
            parsed = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
            return parsed.timestamp() * 1000.0
        except Exception:
            return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric > 1e16:  # ns
            return numeric / 1_000_000.0
        if numeric > 1e13:  # us
            return numeric / 1000.0
        if numeric > 1e10:  # ms
            return numeric
        if numeric > 0:
            return numeric * 1000.0
        return None
    return None


def _collect_spans(raw: Any, out: List[Dict[str, Any]]) -> None:
    if isinstance(raw, dict):
        if any(k in raw for k in ("spanId", "span_id", "id")) and any(
            k in raw for k in ("name", "operationName")
        ):
            out.append(raw)
        for value in raw.values():
            _collect_spans(value, out)
    elif isinstance(raw, list):
        for item in raw:
            _collect_spans(item, out)


def _normalize_trace_payload(trace_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    raw_spans: List[Dict[str, Any]] = []
    _collect_spans(payload, raw_spans)

    spans: List[Dict[str, Any]] = []
    root_span_id: Optional[str] = None
    for raw in raw_spans:
        span_id = raw.get("span_id") or raw.get("spanId") or raw.get("id")
        parent_span_id = raw.get("parent_span_id") or raw.get("parentSpanId")
        if not parent_span_id:
            references = raw.get("references")
            if isinstance(references, list):
                for ref in references:
                    if isinstance(ref, dict) and (
                        ref.get("refType") == "CHILD_OF" or ref.get("type") == "CHILD_OF"
                    ):
                        parent_span_id = ref.get("spanID") or ref.get("spanId")
                        break

        start_ms = _to_epoch_ms(
            raw.get("start_time")
            or raw.get("startTime")
            or raw.get("startTimeUnixNano")
            or raw.get("start_time_unix_nano")
        )
        end_ms = _to_epoch_ms(
            raw.get("end_time")
            or raw.get("endTime")
            or raw.get("endTimeUnixNano")
            or raw.get("end_time_unix_nano")
        )
        duration_ms = raw.get("duration_ms")
        if duration_ms is None:
            duration = raw.get("duration")
            if isinstance(duration, (int, float)):
                duration_ms = duration / 1_000_000.0 if duration > 1e10 else float(duration)
            elif start_ms is not None and end_ms is not None:
                duration_ms = max(end_ms - start_ms, 0.0)

        attrs = _normalize_span_attributes(raw.get("attributes") or raw.get("tags"))
        status_obj = raw.get("status")
        if isinstance(status_obj, dict):
            status_value = status_obj.get("code") or status_obj.get("status_code")
        else:
            status_value = status_obj

        normalized = {
            "span_id": span_id,
            "parent_span_id": parent_span_id,
            "name": raw.get("name") or raw.get("operationName") or "unknown",
            "start_time": start_ms,
            "end_time": end_ms,
            "duration_ms": duration_ms,
            "attributes": attrs,
            "status": status_value,
        }
        spans.append(normalized)
        if not parent_span_id and span_id and root_span_id is None:
            root_span_id = span_id

    if root_span_id is None and spans:
        root_span_id = spans[0].get("span_id")

    return {
        "trace_id": trace_id,
        "root_span_id": root_span_id,
        "spans": spans,
    }


async def _query_trace_cloud(trace_id: str, api_key: str) -> Dict[str, Any]:
    url = settings.EFFICIENT_AI_TRACE_QUERY_URL
    headers: Dict[str, str] = {}
    if api_key:
        headers["X-API-Key"] = api_key
    if settings.EFFICIENT_AI_API_KEY:
        headers["x-efficient-ai-api-key"] = settings.EFFICIENT_AI_API_KEY

    request_url = url.format(trace_id=trace_id) if "{trace_id}" in url else url
    params = {} if "{trace_id}" in url else {"trace_id": trace_id}
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(request_url, params=params, headers=headers)
        response.raise_for_status()
        payload = response.json()
    return _normalize_trace_payload(trace_id, payload)


async def _query_trace_tempo(trace_id: str) -> Dict[str, Any]:
    base = settings.TEMPO_QUERY_URL.rstrip("/")
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(f"{base}/api/traces/{trace_id}")
        response.raise_for_status()
        payload = response.json()
    return _normalize_trace_payload(trace_id, payload)


async def _query_elevenlabs_trace_for_call(
    *,
    db: Session,
    organization_id: UUID,
    workspace_id: UUID,
    call_recording: CallRecording,
    call_data: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    provider_call_id = call_recording.provider_call_id or call_data.get("conversation_id")
    if not provider_call_id:
        return None

    stored = _build_elevenlabs_trace_from_stored_data(call_data, str(provider_call_id))
    if stored:
        return stored

    integration = _resolve_elevenlabs_integration_for_call(
        db=db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        call_recording=call_recording,
        call_data=call_data,
    )
    if integration is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No ElevenLabs integration could be resolved for this call. "
                "Link the provider agent to an integration first."
            ),
        )

    try:
        decrypted_api_key = decrypt_api_key(integration.api_key)
        platform_value = integration.platform.value if hasattr(integration.platform, "value") else str(integration.platform).lower()
        provider_class = get_voice_provider(platform_value)
        provider = provider_class(api_key=decrypted_api_key)
        payload = provider.retrieve_conversation_trace(str(provider_call_id))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to query ElevenLabs trace API: {exc}",
        ) from exc

    status_value = str(payload.get("status") or "").lower().strip()
    if status_value and status_value not in {"done", "failed"}:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trace is not ready yet. ElevenLabs exposes OTLP after conversation completion.",
        )

    otlp_payload = payload.get("otlp_traces")
    if not isinstance(otlp_payload, dict):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No OpenTelemetry trace found in ElevenLabs conversation payload.",
        )

    normalized = normalize_elevenlabs_otlp(
        otlp_payload,
        conversation_id=str(provider_call_id),
        fallback_trace_id=extract_trace_id(otlp_payload),
    )
    transcript = payload.get("transcript")
    if isinstance(transcript, list):
        normalized = enrich_with_turn_metrics(normalized, transcript)
    persisted = persist_provider_trace(
        call_data=call_data,
        provider_platform="elevenlabs",
        organization_id=call_recording.organization_id,
        call_short_id=call_recording.call_short_id,
        trace_payload=normalized,
        source="elevenlabs_api_fetch",
        raw_payload=otlp_payload,
    )
    call_recording.call_data = persisted
    if normalized.get("trace_id"):
        call_recording.trace_id = str(normalized.get("trace_id"))
    call_recording.status = CallRecordingStatus.UPDATED
    db.commit()
    db.refresh(call_recording)
    return normalized


@router.get("/calls/{call_short_id}/trace", response_model=Dict[str, Any])
async def get_call_trace(
    call_short_id: str,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    call_recording = (
        db.query(CallRecording)
        .filter(
            CallRecording.call_short_id == call_short_id,
            CallRecording.organization_id == organization_id,
            CallRecording.workspace_id == workspace_id,
            CallRecording.source.in_(OBSERVABILITY_CALL_SOURCES),
        )
        .first()
    )
    if not call_recording:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")

    call_recording = _prepare_observability_call_recording(db, organization_id, call_recording)

    call_data = call_recording.call_data if isinstance(call_recording.call_data, dict) else {}
    provider_platform = resolve_observability_provider_platform(call_recording, call_data, db=db)
    backend = (settings.TRACING_QUERY_BACKEND or "cloud").strip().lower()
    stored_provider_trace = load_provider_trace(call_data)
    if stored_provider_trace:
        return stored_provider_trace

    elevenlabs_fallback_to_tempo = False
    if provider_platform == "elevenlabs":
        try:
            elevenlabs_trace = await _query_elevenlabs_trace_for_call(
                db=db,
                organization_id=organization_id,
                workspace_id=workspace_id,
                call_recording=call_recording,
                call_data=call_data,
            )
            if elevenlabs_trace:
                return elevenlabs_trace
        except HTTPException as elevenlabs_exc:
            trace_id = call_recording.trace_id or call_data.get("trace_id")
            if backend == "tempo" and trace_id:
                elevenlabs_fallback_to_tempo = True
            else:
                raise elevenlabs_exc

    if provider_platform == "vapi":
        synthetic_trace = build_vapi_synthetic_trace(
            call_data,
            provider_call_id=str(call_recording.provider_call_id or call_data.get("id") or call_short_id),
        )
        if synthetic_trace:
            call_recording.call_data = persist_provider_trace(
                call_data=call_data,
                provider_platform="vapi",
                organization_id=call_recording.organization_id,
                call_short_id=call_recording.call_short_id,
                trace_payload=synthetic_trace,
                source="vapi_synthetic",
            )
            call_recording.trace_id = synthetic_trace.get("trace_id") or call_recording.trace_id
            call_recording.status = CallRecordingStatus.UPDATED
            db.commit()
            return synthetic_trace

    if provider_platform == "retell":
        synthetic_trace = build_retell_synthetic_trace(
            call_data,
            provider_call_id=str(call_recording.provider_call_id or call_data.get("call_id") or call_short_id),
        )
        if synthetic_trace:
            call_recording.call_data = persist_provider_trace(
                call_data=call_data,
                provider_platform="retell",
                organization_id=call_recording.organization_id,
                call_short_id=call_recording.call_short_id,
                trace_payload=synthetic_trace,
                source="retell_synthetic",
            )
            call_recording.trace_id = synthetic_trace.get("trace_id") or call_recording.trace_id
            call_recording.status = CallRecordingStatus.UPDATED
            db.commit()
            return synthetic_trace

    if provider_platform in _LIVE_SYNTHETIC_PLATFORMS or isinstance(call_data.get("live_transcript"), list):
        synthetic_trace = build_live_synthetic_trace(
            call_data,
            provider_call_id=str(call_recording.provider_call_id or call_data.get("id") or call_short_id),
            provider_platform=provider_platform or "external",
            trace_id=str(call_recording.trace_id or call_data.get("trace_id") or "") or None,
        )
        if synthetic_trace:
            call_recording.call_data = persist_provider_trace(
                call_data=call_data,
                provider_platform=provider_platform or "external",
                organization_id=call_recording.organization_id,
                call_short_id=call_recording.call_short_id,
                trace_payload=synthetic_trace,
                source=synthetic_trace.get("trace_source") or "live_synthetic",
            )
            call_recording.trace_id = synthetic_trace.get("trace_id") or call_recording.trace_id
            call_recording.status = CallRecordingStatus.UPDATED
            db.commit()
            return synthetic_trace

    if provider_platform in {"retell", "vapi"}:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No synthetic {provider_platform} trace could be built from stored call data. "
                "Try Refresh on the call to pull the latest provider report."
            ),
        )

    if provider_platform == "elevenlabs" and not elevenlabs_fallback_to_tempo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No provider trace linked to this call yet",
        )

    trace_id = call_recording.trace_id or call_data.get("trace_id")
    if not trace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No trace linked to this call")

    try:
        if backend == "tempo":
            trace_payload = await _query_trace_tempo(trace_id)
            if provider_platform == "elevenlabs":
                trace_payload = {**trace_payload, "trace_source": "efficientai"}
            return trace_payload
        return await _query_trace_cloud(trace_id, api_key)
    except httpx.HTTPStatusError as exc:
        upstream_status = exc.response.status_code
        if upstream_status == status.HTTP_404_NOT_FOUND:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    "Trace not found in the trace store. Spans may have expired, been purged, "
                    "or never exported (check OTLP export and Tempo retention)."
                ),
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Trace backend returned {upstream_status}",
        ) from exc
    except httpx.HTTPError as exc:
        backend_label = "Tempo" if backend == "tempo" else "cloud trace API"
        backend_url = (
            settings.TEMPO_QUERY_URL.rstrip("/")
            if backend == "tempo"
            else settings.EFFICIENT_AI_TRACE_QUERY_URL
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                f"Could not reach {backend_label} at {backend_url}: {exc}. "
                "For local dev with query_backend=tempo, ensure Tempo is running on port 3200."
            ),
        ) from exc


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
            CallRecording.source.in_(OBSERVABILITY_CALL_SOURCES),
        )
        .first()
    )
    if not call_recording:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")

    return _queue_call_evaluation(
        db=db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        call_recording=call_recording,
        evaluator_id=payload.evaluator_id,
        background_tasks=background_tasks,
    )


from app.core.auth.capabilities import REPORTS_GENERATE, REPORTS_VIEW
from app.core.auth.workspace_route_capabilities import apply_workspace_route_capabilities

apply_workspace_route_capabilities(
    router,
    view_capability=REPORTS_VIEW,
    manage_capability=REPORTS_GENERATE,
    run_capability=REPORTS_GENERATE,
)

