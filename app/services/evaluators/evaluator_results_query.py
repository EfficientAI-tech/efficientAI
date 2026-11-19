"""Shared query building and serialization for evaluator results APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import UUID

from sqlalchemy.orm import Session, Query
from sqlalchemy import String, and_, cast, false, or_
from sqlalchemy.dialects.postgresql import JSONB

from app.models.database import EvaluatorResult, Evaluator, Agent, VoiceBundle, Scenario, Persona, CallRecording, CallRecordingSource
from app.models.schemas import (
    AgentResponse,
    EvaluatorResultResponse,
    ScenarioResponse,
    PersonaResponse,
    EvaluatorResponse,
)
from app.services.evaluators.evaluator_result_telephony import enrich_evaluator_result_live_telephony
from app.services.evaluators.evaluator_result_tool_query import apply_tool_call_filters
from app.services.evaluators.evaluator_result_usage_enrichment import (
    enrich_call_data_for_usage_display,
    evaluator_result_ids_with_usage_model,
    usage_enrichment_caches_for_results,
)
from app.services.evaluators.evaluator_result_status import (
    EVALUATION_FATAL_SCORE_ERRORS,
    effective_evaluator_result_status,
    repair_evaluator_result_failed_status_if_needed,
    repair_evaluator_result_status_if_needed,
)
from app.models.enums import EvaluatorResultStatus

_IN_FLIGHT_STATUSES = frozenset(
    {
        EvaluatorResultStatus.QUEUED.value,
        EvaluatorResultStatus.TRANSCRIBING.value,
        EvaluatorResultStatus.EVALUATING.value,
        EvaluatorResultStatus.FETCHING_DETAILS.value,
    }
)

_LIST_QUERY_META_ATTR = "_efficientai_evaluator_list_meta"


def _list_query_meta(query: Query) -> Dict[str, Any]:
    """ORM Query has no portable ``info`` bag — attach list response metadata here."""
    meta = getattr(query, _LIST_QUERY_META_ATTR, None)
    if not isinstance(meta, dict):
        meta = {}
        setattr(query, _LIST_QUERY_META_ATTR, meta)
    return meta


def list_query_usage_cost_usd(query: Query) -> Optional[float]:
    value = _list_query_meta(query).get("usage_cost_usd")
    return float(value) if value is not None else None


def classify_display_status(result: EvaluatorResult) -> str:
    """Match API list/detail effective status semantics."""
    return effective_evaluator_result_status(result)


def is_in_progress_status(display_status: str) -> bool:
    if display_status == EvaluatorResultStatus.FAILED.value:
        return False
    if display_status == EvaluatorResultStatus.COMPLETED.value:
        return False
    return True


def playground_linked_evaluator_result_ids_subquery(db: Session):
    """Evaluator results tied to Agent Playground call recordings."""
    return (
        db.query(CallRecording.evaluator_result_id)
        .filter(
            CallRecording.source == CallRecordingSource.PLAYGROUND,
            CallRecording.evaluator_result_id.isnot(None),
        )
    )


def apply_playground_scope_filter(
    query: Query,
    db: Session,
    *,
    playground: Optional[bool],
    test_agents_only: Optional[bool],
) -> Query:
    playground_ids = playground_linked_evaluator_result_ids_subquery(db)

    if playground is True:
        if test_agents_only is True:
            # Internal test-agent (voice bundle) runs — includes persona/scenario evaluators,
            # excludes Voice AI provider eval runs (Retell/Vapi/ElevenLabs on EvaluatorResult).
            voice_bundle_eval_ids = (
                db.query(CallRecording.evaluator_result_id)
                .filter(
                    CallRecording.source == CallRecordingSource.PLAYGROUND,
                    CallRecording.provider_platform == "voice_bundle",
                    CallRecording.evaluator_result_id.isnot(None),
                )
            )
            query = query.filter(
                EvaluatorResult.provider_platform.is_(None),
                or_(
                    EvaluatorResult.evaluator_id.is_(None),
                    EvaluatorResult.id.in_(voice_bundle_eval_ids),
                ),
            )
        else:
            query = query.filter(
                or_(
                    EvaluatorResult.id.in_(playground_ids),
                    EvaluatorResult.evaluator_id.is_(None),
                )
            )
    else:
        query = query.filter(
            EvaluatorResult.evaluator_id.isnot(None),
            ~EvaluatorResult.id.in_(playground_ids),
        )
    return query


def build_evaluator_results_query(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    evaluator_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    suite_id: Optional[str] = None,
    scenario_id: Optional[str] = None,
    scenario_ids: Optional[Sequence[str]] = None,
    status: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    playground: Optional[bool] = None,
    test_agents_only: Optional[bool] = None,
    unassigned_only: Optional[bool] = None,
    metric_id: Optional[str] = None,
    usage_model: Optional[str] = None,
    tool_use: Optional[str] = None,
    tool_product: Optional[str] = None,
    tool_failures_only: Optional[bool] = None,
    has_tool_calls: Optional[bool] = None,
) -> Query:
    query = db.query(EvaluatorResult).filter(
        EvaluatorResult.organization_id == organization_id,
        EvaluatorResult.workspace_id == workspace_id,
    )

    query = apply_playground_scope_filter(
        query,
        db,
        playground=playground,
        test_agents_only=test_agents_only,
    )

    if unassigned_only:
        query = query.outerjoin(
            Evaluator, EvaluatorResult.evaluator_id == Evaluator.id
        ).filter(
            or_(
                EvaluatorResult.evaluator_id.is_(None),
                Evaluator.suite_id.is_(None),
            )
        )

    if suite_id:
        try:
            suite_uuid = UUID(suite_id)
        except ValueError as exc:
            raise ValueError("Invalid suite_id") from exc
        if not unassigned_only:
            query = query.join(Evaluator, EvaluatorResult.evaluator_id == Evaluator.id)
        query = query.filter(Evaluator.suite_id == suite_uuid)

    if evaluator_id:
        try:
            evaluator_uuid = UUID(evaluator_id)
            query = query.filter(EvaluatorResult.evaluator_id == evaluator_uuid)
        except ValueError as exc:
            raise ValueError("Invalid evaluator_id") from exc

    if agent_id:
        try:
            agent_uuid = UUID(agent_id)
            query = query.filter(EvaluatorResult.agent_id == agent_uuid)
        except ValueError as exc:
            raise ValueError("Invalid agent_id") from exc

    if scenario_id:
        try:
            scenario_uuid = UUID(scenario_id)
            query = query.filter(EvaluatorResult.scenario_id == scenario_uuid)
        except ValueError as exc:
            raise ValueError("Invalid scenario_id") from exc
    elif scenario_ids:
        parsed_ids: List[UUID] = []
        for raw_id in scenario_ids:
            try:
                parsed_ids.append(UUID(str(raw_id)))
            except ValueError as exc:
                raise ValueError("Invalid scenario_id in scenario_ids") from exc
        if parsed_ids:
            query = query.filter(EvaluatorResult.scenario_id.in_(parsed_ids))

    if since is not None and not usage_model:
        query = query.filter(EvaluatorResult.timestamp >= since)
    if until is not None and not usage_model:
        query = query.filter(EvaluatorResult.timestamp <= until)

    if metric_id:
        metric_key = str(metric_id).strip()
        if metric_key:
            query = query.filter(
                EvaluatorResult.metric_scores.isnot(None),
                cast(EvaluatorResult.metric_scores, JSONB).has_key(metric_key),
            )

    if usage_model:
        model_key = str(usage_model).strip()
        if model_key:
            result_ids, usage_micro = evaluator_result_ids_with_usage_model(
                db,
                organization_id=organization_id,
                workspace_id=workspace_id,
                model=model_key,
                since=since,
                until=until,
                playground=playground,
            )
            _list_query_meta(query)["usage_cost_usd"] = usage_micro / 1_000_000
            if result_ids:
                # Ledger attribution already respects Simulations vs Live via usage rows;
                # do not re-apply playground recording filter (judge spend often links
                # playground-linked runs that still appear under Simulations usage).
                query = query.filter(EvaluatorResult.id.in_(result_ids))
            else:
                query = query.filter(false())

    query = apply_tool_call_filters(
        query,
        tool_use=tool_use,
        tool_product=tool_product,
        failures_only=bool(tool_failures_only),
        has_tool_calls=has_tool_calls is True,
    )

    if status:
        normalized = status.strip().lower()
        completed_sql = or_(
            EvaluatorResult.status == EvaluatorResultStatus.COMPLETED.value,
            and_(
                EvaluatorResult.metric_scores.isnot(None),
                EvaluatorResult.status.in_(list(_IN_FLIGHT_STATUSES)),
            ),
        )
        fatal_error_clauses = [
            cast(EvaluatorResult.metric_scores, String).ilike(f'%"{error_key}"%')
            for error_key in EVALUATION_FATAL_SCORE_ERRORS
        ]
        error_only_scores = and_(
            EvaluatorResult.status == EvaluatorResultStatus.COMPLETED.value,
            EvaluatorResult.metric_scores.isnot(None),
            or_(*fatal_error_clauses) if fatal_error_clauses else False,
        )
        if normalized == "completed":
            query = query.filter(completed_sql, ~error_only_scores)
        elif normalized == "failed":
            query = query.filter(
                or_(
                    EvaluatorResult.status == EvaluatorResultStatus.FAILED.value,
                    error_only_scores,
                )
            )
        elif normalized in ("in_progress", "in-progress"):
            query = query.filter(
                EvaluatorResult.status != EvaluatorResultStatus.FAILED.value,
                ~completed_sql,
                ~error_only_scores,
            )
        else:
            raise ValueError("Invalid status filter")

    return query


def _call_data_for_list_row(
    db: Session,
    result: EvaluatorResult,
    *,
    recording_by_result_id: Optional[Dict[UUID, Any]],
    usage_rollup_by_result_id: Optional[Dict[str, Tuple[int, int]]],
    usage_rollup_by_model: Optional[Dict[str, Dict[str, Tuple[int, int]]]],
    usage_rollup_by_role: Optional[Dict[str, Dict[str, Tuple[int, int]]]] = None,
    usage_days_by_result_id: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    call_data = enrich_evaluator_result_live_telephony(db, result, result.call_data)
    recording = (recording_by_result_id or {}).get(result.id)
    rec_data = (
        recording.call_data
        if recording and isinstance(recording.call_data, dict)
        else None
    )
    rollup = (usage_rollup_by_result_id or {}).get(str(result.id))
    rollup_models = (usage_rollup_by_model or {}).get(str(result.id))
    rollup_roles = (usage_rollup_by_role or {}).get(str(result.id))
    return enrich_call_data_for_usage_display(
        call_data if isinstance(call_data, dict) else None,
        recording_call_data=rec_data,
        rollup=rollup,
        rollup_by_model=rollup_models,
        rollup_by_role=rollup_roles,
        usage_on=(usage_days_by_result_id or {}).get(str(result.id)),
    )


def serialize_evaluator_result_row(
    db: Session,
    result: EvaluatorResult,
    *,
    resolve_speaker_segments,
    recording_by_result_id: Optional[Dict[UUID, Any]] = None,
    usage_rollup_by_result_id: Optional[Dict[str, Tuple[int, int]]] = None,
    usage_rollup_by_model: Optional[Dict[str, Dict[str, Tuple[int, int]]]] = None,
    usage_rollup_by_role: Optional[Dict[str, Dict[str, Tuple[int, int]]]] = None,
    usage_days_by_result_id: Optional[Dict[str, str]] = None,
) -> EvaluatorResultResponse:
    repair_evaluator_result_failed_status_if_needed(db, result)
    repair_evaluator_result_status_if_needed(db, result)

    suite_id: Optional[UUID] = None
    evaluator_stub: Optional[Dict[str, Any]] = None
    if result.evaluator_id:
        evaluator = db.query(Evaluator).filter(Evaluator.id == result.evaluator_id).first()
        if evaluator:
            suite_id = evaluator.suite_id
            evaluator_stub = EvaluatorResponse.model_validate(evaluator).model_dump()

    scenario_data = None
    if result.scenario_id:
        scenario = db.query(Scenario).filter(Scenario.id == result.scenario_id).first()
        if scenario:
            scenario_data = ScenarioResponse.model_validate(scenario)

    persona_data = None
    if result.persona_id:
        persona = db.query(Persona).filter(Persona.id == result.persona_id).first()
        if persona:
            persona_data = PersonaResponse.model_validate(persona)

    result_dict: Dict[str, Any] = {
        "id": result.id,
        "result_id": result.result_id,
        "organization_id": result.organization_id,
        "evaluator_id": result.evaluator_id,
        "agent_id": result.agent_id,
        "persona_id": result.persona_id,
        "scenario_id": result.scenario_id,
        "suite_id": suite_id,
        "name": result.name,
        "timestamp": result.timestamp,
        "duration_seconds": result.duration_seconds,
        "status": effective_evaluator_result_status(result),
        "audio_s3_key": result.audio_s3_key,
        "transcription": result.transcription,
        "speaker_segments": resolve_speaker_segments(result),
        "metric_scores": result.metric_scores,
        "celery_task_id": result.celery_task_id,
        "error_message": result.error_message,
        "call_event": result.call_event,
        "provider_call_id": result.provider_call_id,
        "provider_platform": result.provider_platform,
        "call_data": _call_data_for_list_row(
            db,
            result,
            recording_by_result_id=recording_by_result_id,
            usage_rollup_by_result_id=usage_rollup_by_result_id,
            usage_rollup_by_model=usage_rollup_by_model,
            usage_rollup_by_role=usage_rollup_by_role,
            usage_days_by_result_id=usage_days_by_result_id,
        ),
        "synthetic_call_trace_id": result.synthetic_call_trace_id,
        "created_at": result.created_at,
        "updated_at": result.updated_at,
        "created_by": result.created_by,
        "scenario": scenario_data,
        "persona": persona_data,
        "evaluator": evaluator_stub,
    }

    agent = db.query(Agent).filter(Agent.id == result.agent_id).first()
    if agent:
        agent_data = AgentResponse.model_validate(agent).model_dump()
        if agent.voice_bundle_id:
            voice_bundle = db.query(VoiceBundle).filter(VoiceBundle.id == agent.voice_bundle_id).first()
            if voice_bundle:
                agent_data["voice_bundle"] = {
                    "id": str(voice_bundle.id),
                    "name": voice_bundle.name,
                    "bundle_type": voice_bundle.bundle_type,
                    "s2s_model": voice_bundle.s2s_model if voice_bundle.bundle_type == "s2s" else None,
                    "stt_model": voice_bundle.stt_model if voice_bundle.bundle_type == "stt_llm_tts" else None,
                    "llm_model": voice_bundle.llm_model if voice_bundle.bundle_type == "stt_llm_tts" else None,
                    "tts_model": voice_bundle.tts_model if voice_bundle.bundle_type == "stt_llm_tts" else None,
                }
        result_dict["agent"] = agent_data

    call_short_id = None
    call_data = result_dict.get("call_data")
    if isinstance(call_data, dict):
        call_short_id = call_data.get("call_short_id")

    call_recording_source = None
    call_data = result_dict.get("call_data")
    if isinstance(call_data, dict):
        linked_call_short_id = call_data.get("call_short_id")
        if isinstance(linked_call_short_id, str) and linked_call_short_id:
            linked_recording = (
                db.query(CallRecording)
                .filter(
                    CallRecording.call_short_id == linked_call_short_id,
                    CallRecording.organization_id == result.organization_id,
                    CallRecording.workspace_id == result.workspace_id,
                )
                .first()
            )
            if linked_recording and linked_recording.source:
                call_recording_source = linked_recording.source.value
    result_dict["call_recording_source"] = call_recording_source

    from app.services.synthetic_traces.trace_service import lookup_call_trace_status

    result_dict["call_trace_status"] = lookup_call_trace_status(
        db,
        organization_id=result.organization_id,
        workspace_id=result.workspace_id,
        synthetic_call_trace_id=result.synthetic_call_trace_id,
        call_short_id=call_short_id,
    )

    return EvaluatorResultResponse(**result_dict)


def list_evaluator_results_page(
    db: Session,
    query: Query,
    *,
    skip: int,
    limit: int,
    resolve_speaker_segments,
    usage_since: Optional[datetime] = None,
    usage_until: Optional[datetime] = None,
) -> Tuple[List[EvaluatorResultResponse], int]:
    total = query.count()
    results = (
        query.order_by(EvaluatorResult.timestamp.desc()).offset(skip).limit(limit).all()
    )
    from app.services.live_entity_storage import hydrate_evaluator_results

    hydrate_evaluator_results(results)
    recordings, rollups, rollups_by_model, rollups_by_role, usage_days = usage_enrichment_caches_for_results(
        db,
        results,
        usage_since=usage_since.date() if usage_since else None,
        usage_until=usage_until.date() if usage_until else None,
        window_since=usage_since,
        window_until=usage_until,
    )
    items = [
        serialize_evaluator_result_row(
            db,
            row,
            resolve_speaker_segments=resolve_speaker_segments,
            recording_by_result_id=recordings,
            usage_rollup_by_result_id=rollups,
            usage_rollup_by_model=rollups_by_model,
            usage_rollup_by_role=rollups_by_role,
            usage_days_by_result_id=usage_days,
        )
        for row in results
    ]
    return items, total
