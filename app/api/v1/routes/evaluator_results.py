"""Evaluator Results routes."""

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import and_
from uuid import UUID
from typing import List, Optional, Dict, Any

from app.database import get_db
from app.dependencies import get_organization_id, get_workspace_id, get_api_key
from app.models.database import EvaluatorResult, Evaluator, Metric, EvaluatorResultStatus, Scenario, CallRecording, CallRecordingSource, Agent, Integration
import random
from datetime import datetime
from app.models.schemas import (
    EvaluatorResultResponse,
    EvaluatorResultCreate,
    EvaluatorResultCreateManual,
    EvaluatorResultUpdate,
    EvaluatorResultListResponse,
    EvaluatorResultsOverviewResponse,
    EvaluatorResultsAggregateResponse,
)
from app.services.evaluators.evaluator_results_query import (
    build_evaluator_results_query,
    list_evaluator_results_page,
)
from app.services.evaluators.evaluator_results_overview import build_evaluator_results_overview
from app.services.evaluators.evaluator_results_aggregate import compute_evaluator_results_aggregate
from app.services.evaluators.evaluator_result_status import (
    effective_evaluator_result_status,
    repair_evaluator_result_status_if_needed,
)

router = APIRouter(prefix="/evaluator-results", tags=["evaluator-results"])


def _lookup_evaluator_result(
    db: Session,
    id: str,
    organization_id: UUID,
    workspace_id: UUID,
) -> EvaluatorResult | None:
    """Resolve an evaluator result by UUID or 6-digit result_id."""
    try:
        result_uuid = UUID(id)
        return db.query(EvaluatorResult).filter(
            and_(
                EvaluatorResult.id == result_uuid,
                EvaluatorResult.organization_id == organization_id,
                EvaluatorResult.workspace_id == workspace_id,
            )
        ).first()
    except ValueError:
        return db.query(EvaluatorResult).filter(
            and_(
                EvaluatorResult.result_id == id,
                EvaluatorResult.organization_id == organization_id,
                EvaluatorResult.workspace_id == workspace_id,
            )
        ).first()


def _detach_call_recordings_from_evaluator_results(
    db: Session,
    evaluator_result_ids: List[UUID],
) -> None:
    """Clear FK references so observability call rows survive result deletion."""
    if not evaluator_result_ids:
        return
    db.query(CallRecording).filter(
        CallRecording.evaluator_result_id.in_(evaluator_result_ids)
    ).update({CallRecording.evaluator_result_id: None}, synchronize_session=False)


def _derive_speaker_segments_from_call_data(
    call_data: Optional[Dict[str, Any]],
    provider_platform: Optional[str],
) -> Optional[List[Dict[str, Any]]]:
    """Derive speaker segments from provider call_data without persisting duplicates."""
    if not isinstance(call_data, dict):
        return None

    platform = (provider_platform or "").lower()
    segments: List[Dict[str, Any]] = []

    def _append_segment(speaker: str, text: str, start: float, end: float):
        if not text or not str(text).strip():
            return
        segments.append(
            {
                "speaker": speaker,
                "text": str(text).strip(),
                "start": float(start or 0),
                "end": float(end or start or 0),
            }
        )

    if platform == "vapi":
        transcript_object = call_data.get("transcript_object", [])
        if isinstance(transcript_object, list) and transcript_object:
            for entry in transcript_object:
                role = entry.get("role", "")
                if role == "user":
                    speaker = "Speaker 1"
                elif role in ("agent", "assistant", "bot"):
                    speaker = "Speaker 2"
                else:
                    continue
                start = entry.get("seconds_from_start", 0)
                duration_ms = entry.get("duration_ms", 0)
                _append_segment(speaker, entry.get("content", ""), start, start + ((duration_ms or 0) / 1000))
        else:
            artifact = call_data.get("artifact", {})
            messages = call_data.get("messages", []) or (artifact.get("messages", []) if isinstance(artifact, dict) else [])
            if isinstance(messages, list):
                for msg in messages:
                    role = msg.get("role", "")
                    if role == "user":
                        speaker = "Speaker 1"
                    elif role in ("agent", "assistant", "bot"):
                        speaker = "Speaker 2"
                    else:
                        continue
                    start = msg.get("secondsFromStart", 0)
                    duration_ms = msg.get("duration", 0)
                    content = msg.get("message", "") or msg.get("content", "")
                    _append_segment(speaker, content, start, start + ((duration_ms or 0) / 1000))

    elif platform == "retell":
        transcript_object = call_data.get("transcript_object", [])
        if isinstance(transcript_object, list) and transcript_object:
            for entry in transcript_object:
                role = entry.get("role", "")
                speaker = "Speaker 1" if role == "user" else "Speaker 2"
                start = entry.get("start_time", entry.get("timestamp", 0)) or 0
                end = entry.get("end_time", start) or start
                _append_segment(speaker, entry.get("content", "") or entry.get("text", ""), start, end)
        else:
            transcript = call_data.get("transcript", "")
            if isinstance(transcript, str):
                for line in transcript.split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    if line.lower().startswith("user:"):
                        _append_segment("Speaker 1", line.split(":", 1)[1], 0, 0)
                    elif line.lower().startswith("agent:"):
                        _append_segment("Speaker 2", line.split(":", 1)[1], 0, 0)

    elif platform == "elevenlabs":
        transcript_object = call_data.get("transcript_object", [])
        if isinstance(transcript_object, list):
            for entry in transcript_object:
                speaker_raw = str(entry.get("speaker", "")).lower()
                speaker = "Speaker 2" if speaker_raw in ("agent", "assistant", "ai") else "Speaker 1"
                _append_segment(
                    speaker,
                    entry.get("text", ""),
                    entry.get("start", 0),
                    entry.get("end", entry.get("start", 0)),
                )
        elif isinstance(call_data.get("transcript"), list):
            for entry in call_data.get("transcript", []):
                role = entry.get("role", "")
                speaker = "Speaker 2" if role in ("agent", "assistant", "ai") else "Speaker 1"
                t = entry.get("time_in_call_secs", 0)
                _append_segment(speaker, entry.get("message", "") or entry.get("text", ""), t, t)

    elif platform == "smallest":
        transcript_object = call_data.get("transcript_object", [])
        if isinstance(transcript_object, list) and transcript_object:
            for entry in transcript_object:
                speaker_raw = str(entry.get("speaker", "")).lower()
                speaker = "Speaker 2" if speaker_raw in ("agent", "assistant", "ai", "bot") else "Speaker 1"
                _append_segment(
                    speaker,
                    entry.get("text", "") or entry.get("message", ""),
                    entry.get("start", 0),
                    entry.get("end", entry.get("start", 0)),
                )
        elif isinstance(call_data.get("transcript"), list):
            for entry in call_data.get("transcript", []):
                role = str(entry.get("speaker") or entry.get("role") or "").lower()
                speaker = "Speaker 2" if role in ("agent", "assistant", "ai", "bot") else "Speaker 1"
                t = (
                    entry.get("timeInCallSecs", 0)
                    or entry.get("start", 0)
                    or entry.get("timestamp", 0)
                )
                _append_segment(
                    speaker,
                    entry.get("text", "") or entry.get("message", "") or entry.get("content", ""),
                    t,
                    entry.get("end", t),
                )
        elif isinstance(call_data.get("transcript"), str):
            for line in call_data.get("transcript", "").split("\n"):
                line = line.strip()
                if not line or ":" not in line:
                    continue
                speaker_label, text = line.split(":", 1)
                speaker = "Speaker 2" if speaker_label.strip().lower() in ("agent", "assistant", "ai", "bot") else "Speaker 1"
                _append_segment(speaker, text, 0, 0)

    elif platform == "vobiz":
        from app.services.telephony.call_recording_lifecycle import (
            live_transcript_to_messages,
            _timestamp_to_ms,
        )

        messages = call_data.get("messages")
        if not isinstance(messages, list) or not messages:
            live_transcript = call_data.get("live_transcript")
            if isinstance(live_transcript, list) and live_transcript:
                messages = live_transcript_to_messages(live_transcript)
        call_start_ms = _timestamp_to_ms(call_data.get("started_at")) or _timestamp_to_ms(
            call_data.get("startedAt")
        )
        if isinstance(messages, list):
            for index, msg in enumerate(messages):
                if not isinstance(msg, dict):
                    continue
                role = str(msg.get("role", "")).lower()
                speaker = "Speaker 1" if role == "user" else "Speaker 2"
                start_raw = msg.get("start_time", msg.get("secondsFromStart", 0))
                end_raw = msg.get("end_time", msg.get("endTime"))
                start = 0.0
                end = 0.0
                if isinstance(start_raw, (int, float)):
                    if start_raw > 1e10 and call_start_ms:
                        start = max(0.0, (float(start_raw) - float(call_start_ms)) / 1000.0)
                    else:
                        start = float(start_raw / 1000.0 if start_raw > 1e10 else start_raw)
                if isinstance(end_raw, (int, float)):
                    if end_raw > 1e10 and call_start_ms:
                        end = max(start, (float(end_raw) - float(call_start_ms)) / 1000.0)
                    else:
                        end = float(end_raw / 1000.0 if end_raw > 1e10 else end_raw)
                elif start:
                    end = start
                else:
                    start = float(index)
                    end = float(index)
                _append_segment(speaker, msg.get("content", "") or msg.get("message", ""), start, end)

    return segments or None


def _resolve_speaker_segments(result: EvaluatorResult) -> Optional[List[Dict[str, Any]]]:
    """Return speaker segments, preferring persisted values over slim call_data."""
    if result.speaker_segments:
        return result.speaker_segments
    if result.provider_platform and isinstance(result.call_data, dict):
        from app.services.evaluators.call_data_transcript import extract_transcript_from_call_data

        _, segments = extract_transcript_from_call_data(result.call_data, result.provider_platform)
        if segments:
            return segments
        derived = _derive_speaker_segments_from_call_data(result.call_data, result.provider_platform)
        if derived:
            return derived
    return result.speaker_segments


def _resolve_transcription(result: EvaluatorResult, segments: Optional[List[Dict[str, Any]]]) -> Optional[str]:
    if result.transcription and str(result.transcription).strip():
        return result.transcription
    if not segments:
        return result.transcription
    lines = []
    for seg in segments:
        text = str(seg.get("text", "")).strip()
        if not text:
            continue
        speaker = str(seg.get("speaker", "Speaker")).strip() or "Speaker"
        lines.append(f"{speaker}: {text}")
    return "\n".join(lines) if lines else result.transcription


@router.get("/overview", response_model=EvaluatorResultsOverviewResponse)
def get_evaluator_results_overview(
    agent_id: Optional[str] = Query(None, description="When set, return suites for this agent"),
    suite_id: Optional[str] = Query(None, description="When set, return scenarios for this suite"),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Workspace rollups for agent → suite → scenario navigation."""
    agent_uuid: Optional[UUID] = None
    suite_uuid: Optional[UUID] = None
    if agent_id:
        try:
            agent_uuid = UUID(agent_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid agent_id")
    if suite_id:
        try:
            suite_uuid = UUID(suite_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid suite_id")

    return build_evaluator_results_overview(
        db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent_uuid,
        suite_id=suite_uuid,
    )


@router.get("/aggregate", response_model=EvaluatorResultsAggregateResponse)
def get_evaluator_results_aggregate(
    suite_id: Optional[str] = Query(None),
    agent_id: Optional[str] = Query(None),
    scenario_id: Optional[str] = Query(None),
    since: Optional[datetime] = Query(None),
    until: Optional[datetime] = Query(None),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Metric distributions for completed evaluator results in a scope."""
    suite_uuid: Optional[UUID] = None
    agent_uuid: Optional[UUID] = None
    scenario_uuid: Optional[UUID] = None
    if suite_id:
        try:
            suite_uuid = UUID(suite_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid suite_id")
    if agent_id:
        try:
            agent_uuid = UUID(agent_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid agent_id")
    if scenario_id:
        try:
            scenario_uuid = UUID(scenario_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid scenario_id")

    try:
        return compute_evaluator_results_aggregate(
            db,
            organization_id=organization_id,
            workspace_id=workspace_id,
            suite_id=suite_uuid,
            agent_id=agent_uuid,
            scenario_id=scenario_uuid,
            since=since,
            until=until,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=EvaluatorResultListResponse)
def list_evaluator_results(
    skip: int = 0,
    limit: int = 100,
    evaluator_id: Optional[str] = None,
    agent_id: Optional[str] = Query(None, description="Filter by associated agent UUID"),
    suite_id: Optional[str] = Query(None, description="Filter by evaluator suite UUID"),
    scenario_id: Optional[str] = Query(None, description="Filter by scenario UUID"),
    status: Optional[str] = Query(
        None,
        description="Filter by display status: completed, failed, in_progress",
    ),
    since: Optional[datetime] = Query(None),
    until: Optional[datetime] = Query(None),
    unassigned_only: Optional[bool] = Query(
        None,
        description="When true, only legacy/manual results without a suite",
    ),
    playground: Optional[bool] = Query(None, description="If true, only return playground test results (evaluator_id is NULL). If false, exclude playground results. If not provided, exclude playground results by default."),
    test_agents_only: Optional[bool] = Query(None, description="If true, only return Test Agent results (no provider_platform). If false, include all playground results."),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """List evaluator results within the active workspace.

    By default, excludes playground test results (where evaluator_id is NULL).
    Use playground=true to get only playground results, or playground=false to explicitly exclude them.
    Use test_agents_only=true to filter out Voice AI Agent results (those with provider_platform set).
    """
    try:
        query = build_evaluator_results_query(
            db,
            organization_id=organization_id,
            workspace_id=workspace_id,
            evaluator_id=evaluator_id,
            agent_id=agent_id,
            suite_id=suite_id,
            scenario_id=scenario_id,
            status=status,
            since=since,
            until=until,
            playground=playground,
            test_agents_only=test_agents_only,
            unassigned_only=unassigned_only,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    items, total = list_evaluator_results_page(
        db,
        query,
        skip=skip,
        limit=limit,
        resolve_speaker_segments=_resolve_speaker_segments,
    )
    return EvaluatorResultListResponse(items=items, total=total)


@router.get("/{id}", response_model=EvaluatorResultResponse)
def get_evaluator_result(
    id: str,
    include_relations: bool = True,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Get a specific evaluator result in the active workspace by UUID or result_id (6-digit)."""
    from app.models.database import Agent, Persona, Scenario, Evaluator
    from app.models.schemas import AgentResponse, PersonaResponse, ScenarioResponse, EvaluatorResponse
    
    try:
        result_uuid = UUID(id)
        result = db.query(EvaluatorResult).filter(
            and_(
                EvaluatorResult.id == result_uuid,
                EvaluatorResult.organization_id == organization_id,
                EvaluatorResult.workspace_id == workspace_id,
            )
        ).first()
    except ValueError:
        result = db.query(EvaluatorResult).filter(
            and_(
                EvaluatorResult.result_id == id,
                EvaluatorResult.organization_id == organization_id,
                EvaluatorResult.workspace_id == workspace_id,
            )
        ).first()
    
    if not result:
        raise HTTPException(status_code=404, detail="Evaluator result not found")

    from app.services.evaluators.evaluator_result_telephony import enrich_evaluator_result_live_telephony
    from app.services.live_entity_storage import hydrate_evaluator_results

    hydrate_evaluator_results([result])
    repair_evaluator_result_status_if_needed(db, result)

    enriched_call_data = enrich_evaluator_result_live_telephony(db, result, result.call_data)

    call_recording_source = None
    if isinstance(result.call_data, dict):
        linked_call_short_id = result.call_data.get("call_short_id")
        if isinstance(linked_call_short_id, str) and linked_call_short_id:
            linked_recording = (
                db.query(CallRecording)
                .filter(
                    CallRecording.call_short_id == linked_call_short_id,
                    CallRecording.organization_id == organization_id,
                    CallRecording.workspace_id == workspace_id,
                )
                .first()
            )
            if linked_recording and linked_recording.source:
                call_recording_source = linked_recording.source.value
    
    speaker_segments = _resolve_speaker_segments(result)
    transcription = _resolve_transcription(result, speaker_segments)

    # Build response
    response_data = {
        "id": result.id,
        "result_id": result.result_id,
        "organization_id": result.organization_id,
        "evaluator_id": result.evaluator_id,
        "agent_id": result.agent_id,
        "persona_id": result.persona_id,
        "scenario_id": result.scenario_id,
        "name": result.name,
        "timestamp": result.timestamp,
        "duration_seconds": result.duration_seconds,
        "status": effective_evaluator_result_status(result),
        "audio_s3_key": result.audio_s3_key,
        "transcription": transcription,
        "speaker_segments": speaker_segments,
        "metric_scores": result.metric_scores,
        "celery_task_id": result.celery_task_id,
        "error_message": result.error_message,
        # Call tracking fields (for voice AI integrations like Retell)
        "call_event": result.call_event,
        "provider_call_id": result.provider_call_id,
        "provider_platform": result.provider_platform,
        "call_data": enriched_call_data,
        "call_recording_source": call_recording_source,
        "synthetic_call_trace_id": result.synthetic_call_trace_id,
        "created_at": result.created_at,
        "updated_at": result.updated_at,
        "created_by": result.created_by,
    }
    
    # Include related entities if requested
    if include_relations:
        # Get Agent
        agent = db.query(Agent).filter(Agent.id == result.agent_id).first()
        if agent:
            agent_data = AgentResponse.model_validate(agent)
            # Include voice bundle info if agent has voice_bundle_id
            if agent.voice_bundle_id:
                from app.models.database import VoiceBundle
                voice_bundle = db.query(VoiceBundle).filter(VoiceBundle.id == agent.voice_bundle_id).first()
                if voice_bundle:
                    # Add voice bundle info to agent data
                    agent_dict = agent_data.model_dump()
                    agent_dict["voice_bundle"] = {
                        "id": str(voice_bundle.id),
                        "name": voice_bundle.name,
                        "bundle_type": voice_bundle.bundle_type,
                        "s2s_model": voice_bundle.s2s_model if voice_bundle.bundle_type == "s2s" else None,
                        "stt_model": voice_bundle.stt_model if voice_bundle.bundle_type == "stt_llm_tts" else None,
                        "llm_model": voice_bundle.llm_model if voice_bundle.bundle_type == "stt_llm_tts" else None,
                        "tts_model": voice_bundle.tts_model if voice_bundle.bundle_type == "stt_llm_tts" else None,
                    }
                    response_data["agent"] = agent_dict
                else:
                    response_data["agent"] = agent_data
            else:
                response_data["agent"] = agent_data
        
        # Get Persona (only if persona_id is not None)
        if result.persona_id:
            persona = db.query(Persona).filter(Persona.id == result.persona_id).first()
            if persona:
                response_data["persona"] = PersonaResponse.model_validate(persona)
        
        # Get Scenario (only if scenario_id is not None)
        if result.scenario_id:
            scenario = db.query(Scenario).filter(Scenario.id == result.scenario_id).first()
            if scenario:
                response_data["scenario"] = ScenarioResponse.model_validate(scenario)
        
        # Get Evaluator (only if evaluator_id is not None)
        if result.evaluator_id:
            evaluator = db.query(Evaluator).filter(Evaluator.id == result.evaluator_id).first()
            if evaluator:
                response_data["evaluator"] = EvaluatorResponse.model_validate(evaluator)
                response_data["suite_id"] = evaluator.suite_id
    
    return EvaluatorResultResponse(**response_data)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_evaluator_result(
    id: str,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Delete a specific evaluator result in the active workspace by UUID or result_id."""
    try:
        result_uuid = UUID(id)
        result = db.query(EvaluatorResult).filter(
            and_(
                EvaluatorResult.id == result_uuid,
                EvaluatorResult.organization_id == organization_id,
                EvaluatorResult.workspace_id == workspace_id,
            )
        ).first()
    except ValueError:
        result = db.query(EvaluatorResult).filter(
            and_(
                EvaluatorResult.result_id == id,
                EvaluatorResult.organization_id == organization_id,
                EvaluatorResult.workspace_id == workspace_id,
            )
        ).first()
    
    if not result:
        raise HTTPException(status_code=404, detail="Evaluator result not found")

    _detach_call_recordings_from_evaluator_results(db, [result.id])
    db.delete(result)
    db.commit()
    return None


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_evaluator_results_bulk(
    result_ids: List[str] = Query(...),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Delete multiple evaluator results in the active workspace by their IDs."""
    to_delete: List[EvaluatorResult] = []

    for result_id in result_ids:
        try:
            result_uuid = UUID(result_id)
            result = db.query(EvaluatorResult).filter(
                and_(
                    EvaluatorResult.id == result_uuid,
                    EvaluatorResult.organization_id == organization_id,
                    EvaluatorResult.workspace_id == workspace_id,
                )
            ).first()
        except ValueError:
            result = db.query(EvaluatorResult).filter(
                and_(
                    EvaluatorResult.result_id == result_id,
                    EvaluatorResult.organization_id == organization_id,
                    EvaluatorResult.workspace_id == workspace_id,
                )
            ).first()

        if result:
            to_delete.append(result)

    if to_delete:
        _detach_call_recordings_from_evaluator_results(
            db, [row.id for row in to_delete]
        )
        for result in to_delete:
            db.delete(result)

    db.commit()
    return None


@router.get("/{id}/metrics", response_model=dict)
def get_evaluator_result_metrics(
    id: str,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Get metric scores for an evaluator result in the active workspace."""
    try:
        result_uuid = UUID(id)
        result = db.query(EvaluatorResult).filter(
            and_(
                EvaluatorResult.id == result_uuid,
                EvaluatorResult.organization_id == organization_id,
                EvaluatorResult.workspace_id == workspace_id,
            )
        ).first()
    except ValueError:
        result = db.query(EvaluatorResult).filter(
            and_(
                EvaluatorResult.result_id == id,
                EvaluatorResult.organization_id == organization_id,
                EvaluatorResult.workspace_id == workspace_id,
            )
        ).first()
    
    if not result:
        raise HTTPException(status_code=404, detail="Evaluator result not found")
    
    # Get all enabled metrics for the organization
    enabled_metrics = db.query(Metric).filter(
        Metric.organization_id == organization_id,
        Metric.enabled == True
    ).all()
    
    # Build response with metric details
    metrics_response = {}
    if result.metric_scores:
        for metric_id, score_data in result.metric_scores.items():
            metric = next((m for m in enabled_metrics if str(m.id) == metric_id), None)
            if metric:
                metrics_response[metric.name] = {
                    "value": score_data.get("value"),
                    "type": score_data.get("type"),
                    "metric_id": metric_id,
                    "description": metric.description
                }
    
    return {
        "result_id": result.result_id,
        "metrics": metrics_response
    }


@router.get("/{id}/live-events")
async def stream_evaluator_result_live_events(
    id: str,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """SSE stream of live transcript turns for an in-progress eval telephony call."""
    from fastapi.responses import StreamingResponse

    from app.services.evaluators.evaluator_result_telephony import find_evaluator_telephony_recording
    from app.services.telephony.live_transcript_sse import stream_live_transcript_events

    del api_key

    result = _lookup_evaluator_result(db, id, organization_id, workspace_id)
    if not result:
        raise HTTPException(status_code=404, detail="Evaluator result not found")

    call_recording = find_evaluator_telephony_recording(db, result)
    if not call_recording:
        raise HTTPException(status_code=404, detail="No live telephony call linked to this result")

    bound_recording_id = call_recording.id
    call_short_id = call_recording.call_short_id
    bound_result_id = result.id

    def _fetch_recording(session):
        row = (
            session.query(CallRecording)
            .filter(
                CallRecording.id == bound_recording_id,
                CallRecording.evaluator_result_id == bound_result_id,
                CallRecording.source == CallRecordingSource.WEBHOOK,
            )
            .first()
        )
        if row:
            from app.services.live_entity_storage import hydrate_call_recordings

            hydrate_call_recordings([row])
        return row

    async def event_generator():
        async for chunk in stream_live_transcript_events(
            call_short_id=call_short_id,
            bound_recording_id=bound_recording_id,
            fetch_recording=_fetch_recording,
        ):
            yield chunk

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{id}/otel-correlation")
def get_evaluator_result_otel_correlation(
    id: str,
    request: Request,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
    api_key: str = Depends(get_api_key),
):
    """Return OTLP endpoint and correlation env vars for customer Pipecat setup."""
    from app.models.synthetic_trace_schemas import OtelCorrelationInfo
    from app.services.synthetic_traces.trace_service import build_otel_correlation

    del api_key
    result = _lookup_evaluator_result(db, id, organization_id, workspace_id)
    if not result:
        raise HTTPException(status_code=404, detail="Evaluator result not found")
    info = build_otel_correlation(
        db,
        result,
        api_base_url=str(request.base_url).rstrip("/"),
    )
    return OtelCorrelationInfo(**info)


@router.get("/{id}/audio")
async def stream_evaluator_result_audio(
    id: str,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Stream evaluator result audio from S3 or proxy auth-gated provider URLs."""
    import requests as http_requests
    from fastapi.responses import RedirectResponse, StreamingResponse

    from app.core.encryption import decrypt_api_key
    from app.services.storage.audio_delivery import (
        collect_evaluator_result_audio_keys,
        stream_audio_from_keys,
    )
    from app.services.voice_providers.vapi_recording import is_presigned_storage_url
    from app.workers.tasks.process_evaluator_result import _extract_audio_url

    del api_key

    result = _lookup_evaluator_result(db, id, organization_id, workspace_id)
    if not result:
        raise HTTPException(status_code=404, detail="Evaluator result not found")

    storage_stream = stream_audio_from_keys(
        collect_evaluator_result_audio_keys(result),
        filename=f"result_{result.result_id}",
    )
    if storage_stream:
        return storage_stream

    call_data = result.call_data if isinstance(result.call_data, dict) else {}
    platform = (result.provider_platform or "").lower()
    audio_url = _extract_audio_url(call_data, platform)
    if not audio_url:
        raise HTTPException(status_code=404, detail="No recording available")

    if platform in {"retell", "smallest"}:
        return RedirectResponse(audio_url)

    if platform == "vapi" and is_presigned_storage_url(audio_url):
        return RedirectResponse(audio_url)

    decrypted_key = None
    agent = db.query(Agent).filter(Agent.id == result.agent_id).first() if result.agent_id else None
    if agent and agent.voice_ai_integration_id:
        integration = db.query(Integration).filter(
            Integration.id == agent.voice_ai_integration_id,
            Integration.organization_id == organization_id,
        ).first()
        if integration:
            try:
                decrypted_key = decrypt_api_key(integration.api_key)
            except Exception:
                decrypted_key = None

    headers = None
    if platform == "elevenlabs" and decrypted_key:
        headers = {"xi-api-key": decrypted_key}
    elif platform == "vapi" and decrypted_key:
        headers = {"Authorization": f"Bearer {decrypted_key}"}
    elif platform == "vapi":
        return RedirectResponse(audio_url)

    if platform == "elevenlabs" and not headers:
        raise HTTPException(status_code=400, detail="Agent integration not found for ElevenLabs audio")

    upstream = http_requests.get(audio_url, headers=headers, stream=True, timeout=60)
    if upstream.status_code != 200:
        raise HTTPException(
            status_code=upstream.status_code,
            detail=f"Provider audio fetch failed ({upstream.status_code})",
        )

    content_type = upstream.headers.get("content-type", "audio/mpeg")
    return StreamingResponse(
        upstream.iter_content(chunk_size=8192),
        media_type=content_type,
        headers={
            "Content-Disposition": f'inline; filename="result_{result.result_id}.mp3"',
        },
    )


@router.post("", response_model=EvaluatorResultResponse, status_code=status.HTTP_201_CREATED)
def create_evaluator_result_manual(
    result_data: EvaluatorResultCreateManual,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Manually create an evaluator result in the active workspace from an existing audio file.

    The referenced evaluator must already belong to the active workspace.
    """
    evaluator = db.query(Evaluator).filter(
        Evaluator.id == result_data.evaluator_id,
        Evaluator.organization_id == organization_id,
        Evaluator.workspace_id == workspace_id,
    ).first()
    
    if not evaluator:
        raise HTTPException(status_code=404, detail="Evaluator not found")
    
    is_custom = bool(evaluator.custom_prompt)
    
    if is_custom:
        result_name = evaluator.name or "Custom Evaluation"
    else:
        scenario = db.query(Scenario).filter(Scenario.id == evaluator.scenario_id).first()
        result_name = scenario.name if scenario else "Unknown Scenario"
    
    max_attempts = 100
    result_id = None
    for _ in range(max_attempts):
        candidate_id = f"{random.randint(100000, 999999)}"
        existing = db.query(EvaluatorResult).filter(EvaluatorResult.result_id == candidate_id).first()
        if not existing:
            result_id = candidate_id
            break
    
    if not result_id:
        raise HTTPException(status_code=500, detail="Failed to generate unique result ID")
    
    evaluator_result = EvaluatorResult(
        result_id=result_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
        evaluator_id=evaluator.id,
        agent_id=evaluator.agent_id,
        persona_id=evaluator.persona_id,
        scenario_id=evaluator.scenario_id,
        name=result_name,
        duration_seconds=result_data.duration_seconds,
        status=EvaluatorResultStatus.QUEUED.value,
        audio_s3_key=result_data.audio_s3_key
    )
    
    db.add(evaluator_result)
    db.commit()
    db.refresh(evaluator_result)
    
    # Trigger Celery task for transcription and evaluation
    try:
        from app.workers.celery_app import process_evaluator_result_task

        task = process_evaluator_result_task.delay(str(evaluator_result.id))
        evaluator_result.celery_task_id = task.id
        db.commit()
    except Exception as e:
        # If task creation fails, still return the result but log the error
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to trigger Celery task for evaluator result {result_id}: {e}")
    
    return evaluator_result


@router.post("/{id}/re-evaluate", response_model=EvaluatorResultResponse)
def re_evaluate_result(
    id: str,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """
    Re-evaluate an existing evaluator result.

    If the result already has audio in S3, reuses it.  Otherwise attempts to
    download the recording from the voice provider (ElevenLabs / Retell / Vapi),
    uploads it to S3, and stores the key so that audio-dependent quality
    metrics (pitch, jitter, MOS, emotion, etc.) can run alongside the
    LLM-based transcript metrics.
    """
    import logging
    logger = logging.getLogger(__name__)

    try:
        result_uuid = UUID(id)
        result = db.query(EvaluatorResult).filter(
            and_(
                EvaluatorResult.id == result_uuid,
                EvaluatorResult.organization_id == organization_id,
                EvaluatorResult.workspace_id == workspace_id,
            )
        ).first()
    except ValueError:
        result = db.query(EvaluatorResult).filter(
            and_(
                EvaluatorResult.result_id == id,
                EvaluatorResult.organization_id == organization_id,
                EvaluatorResult.workspace_id == workspace_id,
            )
        ).first()

    if not result:
        raise HTTPException(status_code=404, detail="Evaluator result not found")

    if not result.transcription:
        raise HTTPException(
            status_code=400,
            detail="Cannot re-evaluate: this result has no transcription. It must be transcribed first."
        )

    if not result.evaluator_id:
        if result.agent_id and result.persona_id and result.scenario_id:
            from app.api.v1.routes.evaluators import generate_unique_evaluator_id

            evaluator = db.query(Evaluator).filter(
                Evaluator.agent_id == result.agent_id,
                Evaluator.persona_id == result.persona_id,
                Evaluator.scenario_id == result.scenario_id,
                Evaluator.organization_id == organization_id,
                Evaluator.workspace_id == workspace_id,
            ).first()
            if not evaluator:
                new_evaluator_id = generate_unique_evaluator_id(db)
                evaluator = Evaluator(
                    evaluator_id=new_evaluator_id,
                    organization_id=organization_id,
                    workspace_id=workspace_id,
                    agent_id=result.agent_id,
                    persona_id=result.persona_id,
                    scenario_id=result.scenario_id,
                    tags=["auto-created", "test-voice-agent"],
                )
                db.add(evaluator)
                db.commit()
                db.refresh(evaluator)
            result.evaluator_id = evaluator.id
            db.commit()
        elif not result.agent_id:
            raise HTTPException(
                status_code=400,
                detail="Cannot re-evaluate: this result is not linked to an agent or evaluator."
            )

    evaluator = None
    if result.evaluator_id:
        evaluator = db.query(Evaluator).filter(Evaluator.id == result.evaluator_id).first()
        if not evaluator:
            raise HTTPException(status_code=404, detail="Linked evaluator no longer exists")

    # ------------------------------------------------------------------
    # If no audio in S3 yet, try to download from the voice provider
    # ------------------------------------------------------------------
    if not result.audio_s3_key and result.call_data and result.provider_platform:
        try:
            import requests as _http
            import uuid as _uuid
            from app.models.database import Agent, Integration
            from app.core.encryption import decrypt_api_key
            from app.services.storage.s3_service import s3_service

            call_data = result.call_data or {}
            platform = (result.provider_platform or "").lower()
            recording_urls = call_data.get("recording_urls", {})
            provider_payload = call_data.get("provider_payload", {})
            artifact = call_data.get("artifact", {}) if isinstance(call_data, dict) else {}
            recording = artifact.get("recording", {}) if isinstance(artifact, dict) else {}
            mono_recording = recording.get("mono", {}) if isinstance(recording, dict) else {}
            audio_bytes = None
            decrypted_key = None

            # Resolve the integration API key (needed for ElevenLabs auth header)
            agent = db.query(Agent).filter(Agent.id == result.agent_id).first() if result.agent_id else None
            if agent and agent.voice_ai_integration_id:
                integration = db.query(Integration).filter(
                    Integration.id == agent.voice_ai_integration_id,
                    Integration.organization_id == organization_id,
                ).first()
                if integration:
                    decrypted_key = decrypt_api_key(integration.api_key)

            if platform == "elevenlabs":
                audio_url = recording_urls.get("conversation_audio")
                if audio_url and decrypted_key:
                    resp = _http.get(audio_url, headers={"xi-api-key": decrypted_key}, timeout=120)
                    if resp.status_code == 200:
                        audio_bytes = resp.content
            elif platform == "retell":
                audio_url = call_data.get("recording_url")
                if audio_url:
                    resp = _http.get(audio_url, timeout=120)
                    if resp.status_code == 200:
                        audio_bytes = resp.content
            elif platform == "vapi":
                from app.services.voice_providers.vapi_recording import (
                    extract_vapi_recording_url,
                    is_presigned_storage_url,
                )

                audio_url = extract_vapi_recording_url(call_data)
                if audio_url:
                    headers = (
                        None
                        if is_presigned_storage_url(audio_url)
                        else ({"Authorization": f"Bearer {decrypted_key}"} if decrypted_key else None)
                    )
                    resp = _http.get(audio_url, headers=headers, timeout=120)
                    if resp.status_code == 200:
                        audio_bytes = resp.content
            elif platform == "smallest":
                audio_url = (
                    call_data.get("recording_url")
                    or call_data.get("recordingUrl")
                    or recording_urls.get("combined_url")
                    or recording_urls.get("conversation_audio")
                )
                if audio_url:
                    resp = _http.get(audio_url, timeout=120)
                    if resp.status_code == 200:
                        audio_bytes = resp.content

            if audio_bytes:
                content_type = getattr(resp, "headers", {}).get("content-type", "audio/mpeg")
                ext = "wav" if "wav" in content_type else "mp3"
                org_id = str(organization_id)
                audio_s3_key = (
                    f"audio/organizations/{org_id}/evaluations/"
                    f"{result.provider_call_id}/{_uuid.uuid4()}.{ext}"
                )
                s3_service.upload_file_by_key(audio_bytes, audio_s3_key, content_type=content_type)
                result.audio_s3_key = audio_s3_key
                logger.info(
                    f"[Re-evaluate] Downloaded & uploaded audio to S3: "
                    f"{audio_s3_key} ({len(audio_bytes)} bytes)"
                )
            else:
                logger.warning(f"[Re-evaluate] Could not download audio for result {result.result_id}")
        except Exception as audio_err:
            logger.warning(f"[Re-evaluate] Audio download/upload failed: {audio_err}")

    # Reset evaluation state but keep transcription and audio
    result.metric_scores = None
    result.error_message = None
    result.status = EvaluatorResultStatus.QUEUED.value
    db.commit()

    # Dispatch Celery task (it will skip transcription since transcript already exists)
    try:
        from app.workers.celery_app import process_evaluator_result_task

        task = process_evaluator_result_task.delay(str(result.id))
        result.celery_task_id = task.id
        db.commit()
    except Exception as e:
        logger.error(f"Failed to trigger re-evaluate task for result {result.result_id}: {e}")
        result.status = EvaluatorResultStatus.FAILED.value
        result.error_message = f"Failed to queue re-evaluation: {str(e)}"
        db.commit()

    db.refresh(result)
    return result


from app.core.auth.capabilities import EVALS_RUN, EVALS_VIEW
from app.core.auth.workspace_route_capabilities import apply_workspace_route_capabilities

apply_workspace_route_capabilities(
    router,
    view_capability=EVALS_VIEW,
    manage_capability=EVALS_RUN,
    run_capability=EVALS_RUN,
)

