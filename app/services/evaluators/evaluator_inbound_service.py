"""Inbound evaluator suite round-robin for live Vobiz calls."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.models.database import Agent, CallRecording, Evaluator, EvaluatorResult, EvaluatorSuite
from app.models.enums import EvaluatorResultStatus
from app.services.evaluators.evaluator_suite_service import (
    generate_unique_result_id,
    pick_round_robin_combination,
)
from app.services.evaluators.evaluator_result_status import has_meaningful_metric_scores


def find_inbound_suite_for_agent(
    db: Session,
    agent: Agent,
    organization_id: UUID,
    workspace_id: UUID,
) -> Optional[EvaluatorSuite]:
    """Return the active inbound phone evaluator suite for this agent, if any."""
    call_type = (agent.call_type or "outbound").lower()
    call_medium = (agent.call_medium or "phone_call").lower()
    if call_type != "inbound" or call_medium != "phone_call":
        return None

    suite = (
        db.query(EvaluatorSuite)
        .filter(
            EvaluatorSuite.organization_id == organization_id,
            EvaluatorSuite.workspace_id == workspace_id,
            EvaluatorSuite.agent_id == agent.id,
            EvaluatorSuite.is_active.is_(True),
        )
        .first()
    )
    if suite:
        return suite

    fallback = (
        db.query(EvaluatorSuite)
        .filter(
            EvaluatorSuite.organization_id == organization_id,
            EvaluatorSuite.workspace_id == workspace_id,
            EvaluatorSuite.agent_id == agent.id,
        )
        .order_by(EvaluatorSuite.created_at.desc())
        .first()
    )
    if fallback:
        logger.warning(
            "No active inbound evaluator suite for agent {} — falling back to newest (id={})",
            agent.id,
            fallback.id,
        )
    return fallback


def consume_inbound_evaluator_combination(
    db: Session,
    suite: EvaluatorSuite,
) -> Tuple[Evaluator, int, int]:
    """Advance round-robin and return the selected combination evaluator."""
    return pick_round_robin_combination(db, suite)


def create_inbound_evaluator_result(
    db: Session,
    organization_id: UUID,
    workspace_id: UUID,
    evaluator: Evaluator,
) -> EvaluatorResult:
    """Create a queued EvaluatorResult for a live inbound call (no outbound dial)."""
    from app.models.database import Scenario

    scenario = db.query(Scenario).filter(Scenario.id == evaluator.scenario_id).first()
    scenario_name = scenario.name if scenario else "Unknown Scenario"

    result_id = generate_unique_result_id(db)
    evaluator_result = EvaluatorResult(
        result_id=result_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
        evaluator_id=evaluator.id,
        agent_id=evaluator.agent_id,
        persona_id=evaluator.persona_id,
        scenario_id=evaluator.scenario_id,
        name=scenario_name,
        status=EvaluatorResultStatus.QUEUED.value,
        audio_s3_key=None,
    )
    db.add(evaluator_result)
    db.commit()
    db.refresh(evaluator_result)
    return evaluator_result


def _messages_to_transcript(messages: List[Dict[str, Any]]) -> str:
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


def _messages_to_speaker_segments(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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
        segments.append(
            {
                "speaker": speaker,
                "text": msg.get("content", ""),
                "start": float(start),
                "end": float(end),
            }
        )
    return segments


def _resolve_call_duration_seconds(call_data: Dict[str, Any]) -> Optional[float]:
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


def enqueue_linked_evaluator_result_if_ready(
    db: Session,
    call_recording: CallRecording,
) -> bool:
    """
    After a live telephony call ends, copy CallRecording artifacts onto the
    pre-created EvaluatorResult and queue ``process_evaluator_result`` (celery queue).

    Inbound Vobiz creates a QUEUED result at answer time but previously never
    dispatched Celery when the media websocket closed.
    """
    if not call_recording.evaluator_result_id:
        return False

    result = (
        db.query(EvaluatorResult)
        .filter(EvaluatorResult.id == call_recording.evaluator_result_id)
        .first()
    )
    if not result:
        return False
    if result.status != EvaluatorResultStatus.QUEUED.value:
        return False
    if result.celery_task_id:
        # Allow retry when a prior dispatch never produced scores (worker crash / lost task).
        if has_meaningful_metric_scores(result.metric_scores):
            return False
        result.celery_task_id = None
        db.commit()

    db.refresh(call_recording)
    call_data = dict(call_recording.call_data or {})
    call_data.setdefault("call_short_id", call_recording.call_short_id)

    messages = call_data.get("messages")
    if not messages or not isinstance(messages, list):
        live_transcript = call_data.get("live_transcript")
        if isinstance(live_transcript, list) and live_transcript:
            from app.services.telephony.call_recording_lifecycle import live_transcript_to_messages

            messages = live_transcript_to_messages(live_transcript)
            call_data["messages"] = messages

    has_transcript = bool(messages) or bool((call_data.get("transcript") or "").strip())
    has_audio = bool(call_data.get("recording_s3_key"))
    if not has_transcript and not has_audio:
        return False

    if messages:
        result.transcription = _messages_to_transcript(messages)
        result.speaker_segments = _messages_to_speaker_segments(messages)
    elif call_data.get("transcript"):
        result.transcription = str(call_data["transcript"])

    if has_audio:
        result.audio_s3_key = call_data.get("recording_s3_key")

    duration = _resolve_call_duration_seconds(call_data)
    if duration is not None:
        result.duration_seconds = duration

    if call_recording.provider_call_id:
        result.provider_call_id = call_recording.provider_call_id
    if call_recording.provider_platform:
        result.provider_platform = call_recording.provider_platform

    result.call_data = call_data
    db.commit()
    db.refresh(result)

    try:
        from app.workers.celery_app import process_evaluator_result_task

        task = process_evaluator_result_task.delay(str(result.id))
        result.celery_task_id = task.id
        db.commit()
        logger.info(
            "Queued process_evaluator_result for inbound result {} (call {})",
            result.result_id,
            call_recording.call_short_id,
        )
        return True
    except Exception as exc:
        logger.error(
            "Failed to queue process_evaluator_result for inbound result {}: {}",
            result.result_id,
            exc,
            exc_info=True,
        )
        return False
