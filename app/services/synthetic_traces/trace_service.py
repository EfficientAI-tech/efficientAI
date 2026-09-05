"""Open, update, and finalize synthetic call traces."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.models.database import (
    Agent,
    CallRecording,
    EvaluatorResult,
    SyntheticCallTrace,
    SyntheticTraceOtelPayload,
    SyntheticTracePayload,
)
from app.models.synthetic_trace_schemas import VALID_TRACE_TRANSPORTS
from app.utils.call_recordings import generate_unique_call_short_id
from app.services.synthetic_traces.otlp_mapper import (
    annotate_spans_with_display_turn,
    compute_component_aggregates,
    compute_trace_latency_summary,
    derive_turns_from_spans,
    extract_correlation_ids,
    filter_spans_for_trace,
    group_spans_by_call_short_id,
    extract_pipeline_models,
    merge_tier1_and_otel_turns,
    spans_indicate_session_end,
)


OPEN_TRACE_IDLE_CLOSE_SECONDS = 120


def _normalize_turn_row(turn: Dict[str, Any]) -> Dict[str, Any]:
    row = dict(turn)
    if row.get("talk_over") is None:
        row["talk_over"] = False
    if row.get("extra") is None:
        row["extra"] = {}
    return row


def _normalize_turn_rows(turns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [_normalize_turn_row(t) for t in turns]


def resolve_trace_turns(
    trace: SyntheticCallTrace,
    payload: Optional[SyntheticTracePayload],
    otel_payload: Optional[SyntheticTraceOtelPayload],
) -> List[Dict[str, Any]]:
    """Rebuild per-turn metrics from stored payload + OTLP spans."""
    raw_spans = list(otel_payload.spans or []) if otel_payload else []
    scoped_spans = filter_spans_for_trace(raw_spans, call_short_id=trace.call_short_id)
    stored_turns = list(payload.turns or []) if payload else []

    tier1_turns: List[Dict[str, Any]] = []
    for turn in stored_turns:
        num = turn.get("turn_number")
        sut = turn.get("sut_response_latency_ms")
        if num is not None and sut is not None:
            tier1_turns.append(
                {
                    "turn_number": int(num),
                    "sut_response_latency_ms": float(sut),
                    "talk_over": bool(turn.get("talk_over") or False),
                    "extra": dict(turn.get("extra") or {}),
                }
            )

    otel_turns = derive_turns_from_spans(scoped_spans)
    if scoped_spans:
        turns = merge_tier1_and_otel_turns(tier1_turns, otel_turns)
    else:
        turns = stored_turns
    return _normalize_turn_rows(turns)


def enrich_trace_summaries(
    db: Session,
    traces: List[SyntheticCallTrace],
) -> List[Dict[str, Any]]:
    """Recompute latency percentiles from turn data for list views."""
    if not traces:
        return []

    trace_ids = [t.id for t in traces]
    payloads = (
        db.query(SyntheticTracePayload)
        .filter(SyntheticTracePayload.synthetic_call_trace_id.in_(trace_ids))
        .all()
    )
    otel_payloads = (
        db.query(SyntheticTraceOtelPayload)
        .filter(SyntheticTraceOtelPayload.synthetic_call_trace_id.in_(trace_ids))
        .all()
    )
    payload_by_trace = {p.synthetic_call_trace_id: p for p in payloads}
    otel_by_trace = {p.synthetic_call_trace_id: p for p in otel_payloads}

    items: List[Dict[str, Any]] = []
    for trace in traces:
        base = {
            "id": trace.id,
            "evaluator_result_id": trace.evaluator_result_id,
            "agent_id": trace.agent_id,
            "call_short_id": trace.call_short_id,
            "environment": trace.environment,
            "transport": trace.transport,
            "tier": trace.tier,
            "status": trace.status,
            "started_at": trace.started_at,
            "ended_at": trace.ended_at,
            "turn_count": trace.turn_count,
            "response_latency_p50_ms": trace.response_latency_p50_ms,
            "response_latency_p90_ms": trace.response_latency_p90_ms,
            "response_latency_p95_ms": trace.response_latency_p95_ms,
            "response_latency_sample_count": None,
            "component_aggregates": trace.component_aggregates,
            "failure_flags": trace.failure_flags,
            "call_recording_id": trace.call_recording_id,
        }
        turns = resolve_trace_turns(
            trace,
            payload_by_trace.get(trace.id),
            otel_by_trace.get(trace.id),
        )
        if turns:
            summary = compute_trace_latency_summary(turns)
            base["turn_count"] = summary.get("turn_count", base["turn_count"])
            base["response_latency_sample_count"] = summary.get("response_latency_sample_count")
            base["response_latency_p50_ms"] = summary.get("response_latency_p50_ms")
            base["response_latency_p90_ms"] = summary.get("response_latency_p90_ms")
            base["response_latency_p95_ms"] = summary.get("response_latency_p95_ms")
            base["component_aggregates"] = summary.get("component_aggregates")
        items.append(base)
    return items


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def open_trace(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    evaluator_result_id: Optional[UUID] = None,
    agent_id: Optional[UUID] = None,
    persona_id: Optional[UUID] = None,
    scenario_id: Optional[UUID] = None,
    evaluator_id: Optional[UUID] = None,
    call_recording_id: Optional[UUID] = None,
    call_short_id: Optional[str] = None,
    transport: str = "phone",
    provider_platform: Optional[str] = "vobiz",
    environment: str = "pre_prod",
    tier: str = "black_box",
) -> SyntheticCallTrace:
    existing = None
    if evaluator_result_id:
        existing = (
            db.query(SyntheticCallTrace)
            .filter(SyntheticCallTrace.evaluator_result_id == evaluator_result_id)
            .order_by(SyntheticCallTrace.created_at.desc())
            .first()
        )
    if existing and existing.status == "open":
        return existing

    trace = SyntheticCallTrace(
        organization_id=organization_id,
        workspace_id=workspace_id,
        evaluator_result_id=evaluator_result_id,
        agent_id=agent_id,
        persona_id=persona_id,
        scenario_id=scenario_id,
        evaluator_id=evaluator_id,
        call_recording_id=call_recording_id,
        call_short_id=call_short_id,
        environment=environment,
        provider_platform=provider_platform,
        transport=transport,
        tier=tier,
        status="open",
        started_at=_utcnow(),
    )
    db.add(trace)
    db.flush()

    db.add(
        SyntheticTracePayload(
            synthetic_call_trace_id=trace.id,
            workspace_id=workspace_id,
            turns=[],
        )
    )
    db.add(
        SyntheticTraceOtelPayload(
            synthetic_call_trace_id=trace.id,
            workspace_id=workspace_id,
            spans=[],
            trace_ids=[],
        )
    )

    if evaluator_result_id:
        result = db.query(EvaluatorResult).filter(EvaluatorResult.id == evaluator_result_id).first()
        if result:
            result.synthetic_call_trace_id = trace.id

    db.commit()
    db.refresh(trace)
    return trace


def open_trace_for_call_recording(
    db: Session,
    *,
    recording: CallRecording,
    evaluator_result: EvaluatorResult,
) -> Optional[SyntheticCallTrace]:
    """Open a synthetic trace when a phone evaluator call starts."""
    try:
        workspace_id = evaluator_result.workspace_id or recording.workspace_id
        return open_trace(
            db,
            organization_id=recording.organization_id,
            workspace_id=workspace_id,
            evaluator_result_id=evaluator_result.id,
            agent_id=evaluator_result.agent_id,
            persona_id=evaluator_result.persona_id,
            scenario_id=evaluator_result.scenario_id,
            evaluator_id=evaluator_result.evaluator_id,
            call_recording_id=recording.id,
            call_short_id=recording.call_short_id,
            transport="phone",
            provider_platform=recording.provider_platform or "vobiz",
        )
    except Exception as exc:
        logger.warning("Failed to open synthetic call trace: {}", exc)
        return None


def open_trace_session(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    agent_id: Optional[UUID] = None,
    evaluator_result_id: Optional[UUID] = None,
    transport: str = "websocket",
    call_short_id: Optional[str] = None,
) -> SyntheticCallTrace:
    """Mint call_short_id and open a transport-agnostic trace before audio flows."""
    if transport not in VALID_TRACE_TRANSPORTS:
        raise ValueError(f"transport must be one of {VALID_TRACE_TRANSPORTS}")

    if agent_id is not None:
        agent = (
            db.query(Agent)
            .filter(Agent.id == agent_id, Agent.organization_id == organization_id)
            .first()
        )
        if not agent:
            raise ValueError("Agent not found")

    short_id = call_short_id or generate_unique_call_short_id(db)
    provider_platform = "vobiz" if transport == "phone" else None

    persona_id = None
    scenario_id = None
    evaluator_id = None
    if evaluator_result_id:
        result = (
            db.query(EvaluatorResult)
            .filter(
                EvaluatorResult.id == evaluator_result_id,
                EvaluatorResult.organization_id == organization_id,
            )
            .first()
        )
        if result:
            persona_id = result.persona_id
            scenario_id = result.scenario_id
            evaluator_id = result.evaluator_id

    return open_trace(
        db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        evaluator_result_id=evaluator_result_id,
        agent_id=agent_id,
        persona_id=persona_id,
        scenario_id=scenario_id,
        evaluator_id=evaluator_id,
        call_short_id=short_id,
        transport=transport,
        provider_platform=provider_platform,
        tier="component",
    )


def _sync_trace_from_otel_spans(db: Session, trace: SyntheticCallTrace) -> None:
    """Re-derive turn rows and header metrics from stored OTLP spans."""
    otel_payload = (
        db.query(SyntheticTraceOtelPayload)
        .filter(SyntheticTraceOtelPayload.synthetic_call_trace_id == trace.id)
        .first()
    )
    raw_spans = list(otel_payload.spans or []) if otel_payload else []
    spans = filter_spans_for_trace(raw_spans, call_short_id=trace.call_short_id)
    if not spans:
        return

    payload = (
        db.query(SyntheticTracePayload)
        .filter(SyntheticTracePayload.synthetic_call_trace_id == trace.id)
        .first()
    )
    tier1_turns: List[Dict[str, Any]] = []
    if payload and payload.turns:
        for turn in payload.turns:
            num = turn.get("turn_number")
            sut = turn.get("sut_response_latency_ms")
            if num is not None and sut is not None:
                tier1_turns.append(
                    {
                        "turn_number": int(num),
                        "sut_response_latency_ms": float(sut),
                        "talk_over": bool(turn.get("talk_over") or False),
                        "extra": dict(turn.get("extra") or {}),
                    }
                )

    otel_turns = derive_turns_from_spans(spans)
    merged = merge_tier1_and_otel_turns(tier1_turns, otel_turns)
    if payload:
        payload.turns = merged
    else:
        db.add(
            SyntheticTracePayload(
                synthetic_call_trace_id=trace.id,
                workspace_id=trace.workspace_id,
                turns=merged,
            )
        )

    trace.turn_count = len(merged)
    trace.component_aggregates = compute_component_aggregates(merged)
    if otel_turns:
        trace.tier = "mixed" if tier1_turns else "component"
    _update_latency_aggregates(trace, merged)


def close_trace_session(
    db: Session,
    *,
    organization_id: UUID,
    call_short_id: str,
    workspace_id: Optional[UUID] = None,
) -> Optional[SyntheticCallTrace]:
    """Close a trace session without requiring a CallRecording."""
    query = db.query(SyntheticCallTrace).filter(
        SyntheticCallTrace.organization_id == organization_id,
        SyntheticCallTrace.call_short_id == call_short_id,
    )
    if workspace_id is not None:
        query = query.filter(SyntheticCallTrace.workspace_id == workspace_id)
    trace = query.order_by(SyntheticCallTrace.created_at.desc()).first()
    if not trace:
        return None
    return _close_open_trace(db, trace)


def _close_open_trace(db: Session, trace: SyntheticCallTrace) -> SyntheticCallTrace:
    if trace.status in ("closed", "finalized"):
        return trace
    _sync_trace_from_otel_spans(db, trace)
    trace.status = "closed"
    trace.ended_at = _utcnow()
    trace.failure_flags = _compute_failure_flags(trace)
    db.commit()
    db.refresh(trace)
    return trace


def maybe_auto_close_open_trace(
    db: Session,
    trace: SyntheticCallTrace,
    *,
    triggering_spans: Optional[List[Dict[str, Any]]] = None,
    all_spans: Optional[List[Dict[str, Any]]] = None,
) -> SyntheticCallTrace:
    """Close open traces when the session clearly ended or went idle after data arrived."""
    if trace.status in ("closed", "finalized"):
        return trace

    span_batch = list(triggering_spans or [])
    if all_spans:
        span_batch = span_batch + list(all_spans)

    if span_batch and spans_indicate_session_end(span_batch):
        return _close_open_trace(db, trace)

    if trace.turn_count < 1:
        return trace

    updated_at = trace.updated_at or trace.started_at
    if not updated_at:
        return trace
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    idle_seconds = (_utcnow() - updated_at).total_seconds()
    if idle_seconds >= OPEN_TRACE_IDLE_CLOSE_SECONDS:
        return _close_open_trace(db, trace)

    return trace


def link_trace_to_call_recording(
    db: Session,
    *,
    organization_id: UUID,
    call_short_id: str,
    call_recording_id: UUID,
) -> Optional[SyntheticCallTrace]:
    trace = (
        db.query(SyntheticCallTrace)
        .filter(
            SyntheticCallTrace.organization_id == organization_id,
            SyntheticCallTrace.call_short_id == call_short_id,
        )
        .order_by(SyntheticCallTrace.created_at.desc())
        .first()
    )
    if not trace:
        return None
    trace.call_recording_id = call_recording_id
    db.commit()
    db.refresh(trace)
    return trace


def link_trace_to_evaluator_result(
    db: Session,
    *,
    organization_id: UUID,
    call_short_id: str,
    evaluator_result_id: UUID,
    call_recording_id: Optional[UUID] = None,
) -> Optional[SyntheticCallTrace]:
    trace = (
        db.query(SyntheticCallTrace)
        .filter(
            SyntheticCallTrace.organization_id == organization_id,
            SyntheticCallTrace.call_short_id == call_short_id,
        )
        .order_by(SyntheticCallTrace.created_at.desc())
        .first()
    )
    if not trace:
        return None
    trace.evaluator_result_id = evaluator_result_id
    if call_recording_id:
        trace.call_recording_id = call_recording_id
    result = (
        db.query(EvaluatorResult)
        .filter(
            EvaluatorResult.id == evaluator_result_id,
            EvaluatorResult.organization_id == organization_id,
        )
        .first()
    )
    if result:
        result.synthetic_call_trace_id = trace.id
    db.commit()
    db.refresh(trace)
    return trace


OBSERVABILITY_TRACES_API_PATH = "/api/v1/observability/traces"


def build_session_otel_correlation(
    *,
    api_base_url: str,
    call_short_id: str,
    workspace_id: UUID,
    evaluator_result_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    otlp_endpoint = f"{api_base_url.rstrip('/')}{OBSERVABILITY_TRACES_API_PATH}"
    env_vars: Dict[str, str] = {
        "EFFICIENTAI_OTLP_ENDPOINT": otlp_endpoint,
        "EFFICIENTAI_API_KEY": "<your-efficientai-api-key>",
        "EFFICIENTAI_WORKSPACE_ID": str(workspace_id),
        "EFFICIENTAI_CALL_SHORT_ID": call_short_id,
    }
    span_attrs: Dict[str, str] = {
        "efficientai.call_short_id": call_short_id,
        "efficientai.workspace_id": str(workspace_id),
        "efficientai.environment": "pre_prod",
    }
    headers: Dict[str, str] = {
        "X-API-Key": "<your-efficientai-api-key>",
        "X-Workspace-Id": str(workspace_id),
        "X-EfficientAI-Call-Short-Id": call_short_id,
    }
    if evaluator_result_id:
        env_vars["EFFICIENTAI_EVALUATOR_RESULT_ID"] = str(evaluator_result_id)
        span_attrs["efficientai.evaluator_result_id"] = str(evaluator_result_id)
        headers["X-EfficientAI-Run-Id"] = str(evaluator_result_id)

    return {
        "otlp_endpoint": otlp_endpoint,
        "api_key_header": "X-API-Key",
        "suggested_env_vars": env_vars,
        "suggested_otlp_headers": headers,
        "suggested_span_attributes": span_attrs,
    }


def backfill_missing_traces_from_call_recordings(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    limit: int = 50,
) -> int:
    """Create synthetic traces for phone evaluator recordings that never got one."""
    linked_result_ids = {
        row[0]
        for row in db.query(SyntheticCallTrace.evaluator_result_id)
        .filter(
            SyntheticCallTrace.organization_id == organization_id,
            SyntheticCallTrace.workspace_id == workspace_id,
            SyntheticCallTrace.evaluator_result_id.isnot(None),
        )
        .all()
    }

    recordings = (
        db.query(CallRecording)
        .filter(
            CallRecording.organization_id == organization_id,
            CallRecording.workspace_id == workspace_id,
            CallRecording.evaluator_result_id.isnot(None),
            CallRecording.provider_platform == "vobiz",
        )
        .order_by(CallRecording.created_at.desc())
        .limit(limit * 3)
        .all()
    )

    created = 0
    for recording in recordings:
        if recording.evaluator_result_id in linked_result_ids:
            continue
        result = (
            db.query(EvaluatorResult)
            .filter(EvaluatorResult.id == recording.evaluator_result_id)
            .first()
        )
        if not result:
            continue
        trace = open_trace_for_call_recording(db, recording=recording, evaluator_result=result)
        if not trace:
            continue
        linked_result_ids.add(recording.evaluator_result_id)
        created += 1
        event = (recording.call_event or "").lower()
        if event in {"call_ended", "completed", "failed"} or (
            isinstance(recording.call_data, dict) and recording.call_data.get("ended_at")
        ):
            finalize_trace(db, call_short_id=recording.call_short_id)
        if created >= limit:
            break
    return created


def get_trace_for_result(
    db: Session,
    *,
    organization_id: UUID,
    evaluator_result_id: UUID,
    workspace_id: Optional[UUID] = None,
    auto_close: bool = True,
) -> Optional[SyntheticCallTrace]:
    query = db.query(SyntheticCallTrace).filter(
        SyntheticCallTrace.organization_id == organization_id,
        SyntheticCallTrace.evaluator_result_id == evaluator_result_id,
    )
    if workspace_id is not None:
        query = query.filter(SyntheticCallTrace.workspace_id == workspace_id)
    trace = query.order_by(SyntheticCallTrace.created_at.desc()).first()
    if trace and auto_close:
        trace = maybe_auto_close_open_trace(db, trace)
    return trace


def get_trace_by_id(
    db: Session,
    *,
    organization_id: UUID,
    trace_id: UUID,
    workspace_id: Optional[UUID] = None,
) -> Optional[SyntheticCallTrace]:
    query = db.query(SyntheticCallTrace).filter(
        SyntheticCallTrace.id == trace_id,
        SyntheticCallTrace.organization_id == organization_id,
    )
    if workspace_id is not None:
        query = query.filter(SyntheticCallTrace.workspace_id == workspace_id)
    trace = query.first()
    if trace:
        trace = maybe_auto_close_open_trace(db, trace)
    return trace


def get_trace_by_call_short_id(
    db: Session,
    *,
    organization_id: UUID,
    call_short_id: str,
    workspace_id: Optional[UUID] = None,
) -> Optional[SyntheticCallTrace]:
    query = db.query(SyntheticCallTrace).filter(
        SyntheticCallTrace.organization_id == organization_id,
        SyntheticCallTrace.call_short_id == call_short_id,
    )
    if workspace_id is not None:
        query = query.filter(SyntheticCallTrace.workspace_id == workspace_id)
    trace = query.order_by(SyntheticCallTrace.created_at.desc()).first()
    if trace:
        trace = maybe_auto_close_open_trace(db, trace)
    return trace


def list_traces(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    skip: int = 0,
    limit: int = 50,
    status: Optional[str] = None,
) -> tuple[List[SyntheticCallTrace], int]:
    backfill_missing_traces_from_call_recordings(
        db, organization_id=organization_id, workspace_id=workspace_id
    )
    query = db.query(SyntheticCallTrace).filter(
        SyntheticCallTrace.organization_id == organization_id,
        SyntheticCallTrace.workspace_id == workspace_id,
    )
    if status:
        if status == "closed":
            query = query.filter(SyntheticCallTrace.status.in_(("closed", "finalized")))
        else:
            query = query.filter(SyntheticCallTrace.status == status)
    total = query.count()
    rows = (
        query.order_by(SyntheticCallTrace.started_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return rows, total


def build_otlp_setup_info(*, api_base_url: str) -> Dict[str, Any]:
    otlp_endpoint = f"{api_base_url.rstrip('/')}{OBSERVABILITY_TRACES_API_PATH}"
    sessions_endpoint = f"{api_base_url.rstrip('/')}{OBSERVABILITY_TRACES_API_PATH}/sessions"
    pipecat_example = f'''# pip install -e 'path/to/efficientAI[otel]'
from efficientai.integrations.efficientai_traces import (
    close_trace_session,
    ensure_trace_session,
    require_deployment_trace_env,
    resolve_trace_transport,
    setup_pipecat_worker_tracing,
)

require_deployment_trace_env()  # EFFICIENTAI_API_KEY + EFFICIENTAI_WORKSPACE_ID

async def run_bot(transport, runner_args):
    trace_transport = resolve_trace_transport(runner_args, transport)
    trace_ctx = await ensure_trace_session(transport=trace_transport)
    tracing = setup_pipecat_worker_tracing(trace_ctx)

    worker = PipelineWorker(
        pipeline,
        enable_tracing=True,
        additional_span_attributes=tracing["additional_span_attributes"],
    )

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        await worker.cancel()
        await close_trace_session(trace_ctx)

# Pipecat runner: http://localhost:7860/client — pick WebRTC or WebSocket in the UI.
'''
    return {
        "otlp_endpoint": otlp_endpoint,
        "api_key_header": "X-API-Key",
        "one_time_env_vars": {
            "EFFICIENTAI_API_KEY": "<your-efficientai-api-key>",
            "EFFICIENTAI_WORKSPACE_ID": "<workspace-uuid>",
            "EFFICIENTAI_OTLP_ENDPOINT": otlp_endpoint,
        },
        "transport_options": {
            "webrtc": "Default — Pipecat runner at http://localhost:7860/client",
        },
        "sessions_endpoint": sessions_endpoint,
        "workspace_header": "X-Workspace-Id",
        "setup_steps": [
            {
                "title": "Install the tracing package",
                "detail": (
                    "In your Pipecat project: "
                    "uv pip install -e '/path/to/efficientAI[otel]' "
                    "and pipecat extras (deepgram, openai, cartesia, webrtc, runner)."
                ),
            },
            {
                "title": "Add env vars to Pipecat .env",
                "detail": (
                    "EFFICIENTAI_API_KEY, EFFICIENTAI_WORKSPACE_ID, plus your STT/LLM/TTS keys. "
                    "See docs/examples/pipecat_multi_agent_webrtc_tracing.py "
                    "(or pipecat_multi_provider_webrtc_tracing.py)."
                ),
            },
            {
                "title": "Enable tracing in bot.py",
                "detail": (
                    "Call ensure_trace_session() on connect, "
                    "PipelineWorker(..., enable_tracing=True), "
                    "close_trace_session() on disconnect."
                ),
            },
            {
                "title": "Run a local WebRTC call",
                "detail": "uv run bot.py → open :7860/client → WebRTC → talk 2–3 turns → disconnect.",
            },
            {
                "title": "View results here",
                "detail": "Refresh the Traces tab — each call shows STT, LLM, TTS, and response time per turn.",
            },
        ],
        "per_call_correlation": {
            "session_api": sessions_endpoint,
            "header": "X-EfficientAI-Call-Short-Id",
            "span_attribute": "efficientai.call_short_id",
            "workspace_span_attribute": "efficientai.workspace_id",
            "note": (
                "Each call gets a 6-digit call ID when your bot starts. "
                "Spans must include efficientai.call_short_id and efficientai.workspace_id. "
                "Export to POST /api/v1/observability/traces with headers X-API-Key and X-Workspace-Id."
            ),
        },
        "suggested_span_resource_attributes": {
            "efficientai.environment": "pre_prod",
            "efficientai.workspace_id": "<workspace-uuid>",
        },
        "pipecat_python_example": pipecat_example,
    }


def record_tier1_turns(
    db: Session,
    trace: SyntheticCallTrace,
    turns: List[Dict[str, Any]],
) -> None:
    if not turns:
        return
    payload = (
        db.query(SyntheticTracePayload)
        .filter(SyntheticTracePayload.synthetic_call_trace_id == trace.id)
        .first()
    )
    if not payload:
        payload = SyntheticTracePayload(
            synthetic_call_trace_id=trace.id,
            workspace_id=trace.workspace_id,
            turns=[],
        )
        db.add(payload)

    otel_payload = (
        db.query(SyntheticTraceOtelPayload)
        .filter(SyntheticTraceOtelPayload.synthetic_call_trace_id == trace.id)
        .first()
    )
    otel_turns = derive_turns_from_spans(otel_payload.spans if otel_payload else [])
    payload.turns = merge_tier1_and_otel_turns(turns, otel_turns)
    trace.turn_count = len(payload.turns)
    _update_latency_aggregates(trace, payload.turns)
    if otel_turns:
        trace.tier = "mixed" if turns else "component"
    db.commit()


def ingest_otlp_spans(
    db: Session,
    *,
    organization_id: UUID,
    spans: List[Dict[str, Any]],
    header_evaluator_result_id: Optional[str] = None,
    header_agent_id: Optional[str] = None,
    header_call_short_id: Optional[str] = None,
    workspace_id: Optional[UUID] = None,
) -> tuple[SyntheticCallTrace | None, int, bool]:
    if not spans:
        return None, 0, False

    groups = group_spans_by_call_short_id(spans, header_call_short_id=header_call_short_id)
    last_trace: Optional[SyntheticCallTrace] = None
    total_accepted = 0
    any_correlated = False

    for group_call_short_id, group_spans in groups.items():
        trace, accepted, correlated = _ingest_otlp_span_group(
            db,
            organization_id=organization_id,
            spans=group_spans,
            header_evaluator_result_id=header_evaluator_result_id,
            header_agent_id=header_agent_id,
            header_call_short_id=group_call_short_id or header_call_short_id,
            workspace_id=workspace_id,
        )
        total_accepted += accepted
        any_correlated = any_correlated or correlated
        if trace is not None:
            last_trace = trace

    return last_trace, total_accepted, any_correlated


def _ingest_otlp_span_group(
    db: Session,
    *,
    organization_id: UUID,
    spans: List[Dict[str, Any]],
    header_evaluator_result_id: Optional[str] = None,
    header_agent_id: Optional[str] = None,
    header_call_short_id: Optional[str] = None,
    workspace_id: Optional[UUID] = None,
) -> tuple[SyntheticCallTrace | None, int, bool]:
    if not spans:
        return None, 0, False

    correlation = extract_correlation_ids(spans)
    evaluator_result_id = (
        header_evaluator_result_id
        or correlation.get("evaluator_result_id")
    )
    call_short_id = correlation.get("call_short_id") or header_call_short_id
    _ = header_agent_id or correlation.get("agent_id")

    trace: Optional[SyntheticCallTrace] = None
    correlated = False

    if evaluator_result_id:
        try:
            result_uuid = UUID(str(evaluator_result_id))
            trace = get_trace_for_result(
                db,
                organization_id=organization_id,
                evaluator_result_id=result_uuid,
                workspace_id=workspace_id,
                auto_close=False,
            )
            if not trace:
                result = (
                    db.query(EvaluatorResult)
                    .filter(
                        EvaluatorResult.id == result_uuid,
                        EvaluatorResult.organization_id == organization_id,
                    )
                    .first()
                )
                if result and workspace_id is not None and result.workspace_id != workspace_id:
                    result = None
                if result:
                    trace = open_trace(
                        db,
                        organization_id=organization_id,
                        workspace_id=result.workspace_id,
                        evaluator_result_id=result.id,
                        agent_id=result.agent_id,
                        persona_id=result.persona_id,
                        scenario_id=result.scenario_id,
                        evaluator_id=result.evaluator_id,
                        call_short_id=call_short_id,
                        transport="phone",
                        tier="component",
                    )
            correlated = trace is not None
        except ValueError:
            trace = None

    if not trace and call_short_id:
        trace = get_trace_by_call_short_id(
            db,
            organization_id=organization_id,
            call_short_id=call_short_id,
            workspace_id=workspace_id,
        )
        correlated = trace is not None

    if not trace and call_short_id and workspace_id:
        transport = correlation.get("transport") or "custom"
        if transport not in VALID_TRACE_TRANSPORTS:
            transport = "custom"
        try:
            trace = open_trace_session(
                db,
                organization_id=organization_id,
                workspace_id=workspace_id,
                call_short_id=call_short_id,
                transport=transport,
            )
            correlated = True
        except ValueError:
            trace = None

    if not trace:
        return None, len(spans), False

    if trace.status in ("closed", "finalized"):
        trace.status = "open"
        trace.ended_at = None

    otel_payload = (
        db.query(SyntheticTraceOtelPayload)
        .filter(SyntheticTraceOtelPayload.synthetic_call_trace_id == trace.id)
        .first()
    )
    if not otel_payload:
        otel_payload = SyntheticTraceOtelPayload(
            synthetic_call_trace_id=trace.id,
            workspace_id=trace.workspace_id,
            spans=[],
            trace_ids=[],
        )
        db.add(otel_payload)

    existing_spans: List[Dict[str, Any]] = list(otel_payload.spans or [])
    existing_ids = {(s.get("trace_id"), s.get("span_id")) for s in existing_spans}
    new_trace_ids = set(otel_payload.trace_ids or [])

    for span in spans:
        key = (span.get("trace_id"), span.get("span_id"))
        if key in existing_ids:
            continue
        existing_spans.append(span)
        existing_ids.add(key)
        if span.get("trace_id"):
            new_trace_ids.add(span["trace_id"])

    otel_payload.spans = existing_spans
    otel_payload.trace_ids = sorted(new_trace_ids)

    scoped_spans = filter_spans_for_trace(existing_spans, call_short_id=trace.call_short_id)

    payload = (
        db.query(SyntheticTracePayload)
        .filter(SyntheticTracePayload.synthetic_call_trace_id == trace.id)
        .first()
    )
    tier1_turns = list(payload.turns or []) if payload else []
    otel_turns = derive_turns_from_spans(scoped_spans)
    merged = merge_tier1_and_otel_turns(tier1_turns, otel_turns)

    if payload:
        payload.turns = merged
    else:
        db.add(
            SyntheticTracePayload(
                synthetic_call_trace_id=trace.id,
                workspace_id=trace.workspace_id,
                turns=merged,
            )
        )

    trace.turn_count = len(merged)
    trace.component_aggregates = compute_component_aggregates(merged)
    transport = correlation.get("transport")
    if transport in VALID_TRACE_TRANSPORTS:
        trace.transport = transport
    if otel_turns:
        trace.tier = "mixed" if tier1_turns else "component"
    _update_latency_aggregates(trace, merged)
    trace = maybe_auto_close_open_trace(
        db,
        trace,
        triggering_spans=spans,
        all_spans=existing_spans,
    )
    db.commit()
    db.refresh(trace)
    return trace, len(spans), correlated


def ingest_json_spans(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    call_short_id: str,
    agent_id: Optional[UUID] = None,
    spans: List[Dict[str, Any]],
) -> tuple[SyntheticCallTrace | None, int, bool]:
    """Convert simple JSON span payloads into OTLP-shaped records for ingest."""
    import uuid as _uuid

    otlp_spans: List[Dict[str, Any]] = []
    for idx, span in enumerate(spans):
        name = str(span.get("name") or "unknown")
        turn_number = int(span.get("turn_number") or 1)
        attrs: Dict[str, Any] = dict(span.get("attributes") or {})
        attrs.setdefault("gen_ai.operation.name", name.lower())
        attrs.setdefault("turn.number", turn_number)
        ttfb_ms = span.get("ttfb_ms")
        if ttfb_ms is not None:
            attrs.setdefault("metrics.ttfb", float(ttfb_ms) / 1000.0)
        otlp_spans.append(
            {
                "trace_id": f"json-{call_short_id}",
                "span_id": f"json-{idx}-{_uuid.uuid4().hex[:8]}",
                "name": name,
                "attributes": attrs,
            }
        )

    return ingest_otlp_spans(
        db,
        organization_id=organization_id,
        spans=otlp_spans,
        header_call_short_id=call_short_id,
        header_agent_id=str(agent_id) if agent_id else None,
        workspace_id=workspace_id,
    )


def finalize_trace(
    db: Session,
    *,
    call_short_id: str,
    tier1_turns: Optional[List[Dict[str, Any]]] = None,
) -> Optional[SyntheticCallTrace]:
    recording = (
        db.query(CallRecording)
        .filter(CallRecording.call_short_id == call_short_id)
        .first()
    )
    if not recording:
        logger.warning("finalize_trace: no CallRecording for call_short_id={}", call_short_id)
        return None

    trace = None
    if recording.evaluator_result_id:
        trace = (
            db.query(SyntheticCallTrace)
            .filter(SyntheticCallTrace.evaluator_result_id == recording.evaluator_result_id)
            .order_by(SyntheticCallTrace.created_at.desc())
            .first()
        )
    if not trace:
        trace = (
            db.query(SyntheticCallTrace)
            .filter(SyntheticCallTrace.call_short_id == call_short_id)
            .order_by(SyntheticCallTrace.created_at.desc())
            .first()
        )

    if not trace:
        if not recording.evaluator_result_id:
            return None
        result = (
            db.query(EvaluatorResult)
            .filter(EvaluatorResult.id == recording.evaluator_result_id)
            .first()
        )
        if not result:
            return None
        trace = open_trace(
            db,
            organization_id=recording.organization_id,
            workspace_id=recording.workspace_id,
            evaluator_result_id=result.id,
            agent_id=result.agent_id,
            persona_id=result.persona_id,
            scenario_id=result.scenario_id,
            evaluator_id=result.evaluator_id,
            call_recording_id=recording.id,
            call_short_id=call_short_id,
            transport="phone",
            provider_platform=recording.provider_platform or "vobiz",
        )

    if tier1_turns:
        record_tier1_turns(db, trace, tier1_turns)
        db.refresh(trace)

    trace.status = "closed"
    trace.ended_at = _utcnow()
    trace.call_recording_id = recording.id
    trace.call_short_id = call_short_id
    trace.failure_flags = _compute_failure_flags(trace)
    db.commit()
    db.refresh(trace)
    return trace


def load_trace_detail(
    db: Session,
    trace: SyntheticCallTrace,
) -> Dict[str, Any]:
    payload = (
        db.query(SyntheticTracePayload)
        .filter(SyntheticTracePayload.synthetic_call_trace_id == trace.id)
        .first()
    )
    otel_payload = (
        db.query(SyntheticTraceOtelPayload)
        .filter(SyntheticTraceOtelPayload.synthetic_call_trace_id == trace.id)
        .first()
    )
    raw_spans = list(otel_payload.spans or []) if otel_payload else []
    scoped_spans = filter_spans_for_trace(raw_spans, call_short_id=trace.call_short_id)
    otel_spans = annotate_spans_with_display_turn(scoped_spans)
    turns = resolve_trace_turns(trace, payload, otel_payload)
    latency_summary = compute_trace_latency_summary(turns) if turns else {}

    return {
        "trace": trace,
        "turns": turns,
        "otel_spans": otel_spans,
        "otel_trace_ids": list(otel_payload.trace_ids or []) if otel_payload else [],
        "latency_summary": latency_summary,
        "pipeline_models": extract_pipeline_models(otel_spans),
    }


def build_otel_correlation(
    db: Session,
    result: EvaluatorResult,
    *,
    api_base_url: str,
) -> Dict[str, Any]:
    trace = None
    if result.synthetic_call_trace_id:
        trace = get_trace_by_id(
            db,
            organization_id=result.organization_id,
            trace_id=result.synthetic_call_trace_id,
        )
    if not trace:
        trace = get_trace_for_result(
            db,
            organization_id=result.organization_id,
            evaluator_result_id=result.id,
        )

    call_short_id = trace.call_short_id if trace else None
    if not call_short_id and result.call_data and isinstance(result.call_data, dict):
        call_short_id = result.call_data.get("call_short_id")

    otlp_endpoint = f"{api_base_url.rstrip('/')}{OBSERVABILITY_TRACES_API_PATH}"
    env_vars = {
        "EFFICIENTAI_OTLP_ENDPOINT": otlp_endpoint,
        "EFFICIENTAI_API_KEY": "<your-efficientai-api-key>",
    }
    if result.workspace_id:
        env_vars["EFFICIENTAI_WORKSPACE_ID"] = str(result.workspace_id)
    if call_short_id:
        env_vars["EFFICIENTAI_CALL_SHORT_ID"] = call_short_id

    span_attrs: Dict[str, str] = {
        "efficientai.evaluator_result_id": str(result.id),
        "efficientai.call_short_id": call_short_id or "",
        "efficientai.environment": "pre_prod",
    }
    if result.workspace_id:
        span_attrs["efficientai.workspace_id"] = str(result.workspace_id)

    return {
        "evaluator_result_id": result.id,
        "synthetic_call_trace_id": trace.id if trace else result.synthetic_call_trace_id,
        "call_short_id": call_short_id,
        "agent_id": result.agent_id,
        "otlp_endpoint": otlp_endpoint,
        "suggested_env_vars": env_vars,
        "suggested_span_attributes": span_attrs,
    }


def _update_latency_aggregates(trace: SyntheticCallTrace, turns: List[Dict[str, Any]]) -> None:
    summary = compute_trace_latency_summary(turns)
    if summary.get("response_latency_p50_ms") is not None:
        trace.response_latency_p50_ms = summary["response_latency_p50_ms"]
        trace.response_latency_p90_ms = summary.get("response_latency_p90_ms")
        trace.response_latency_p95_ms = summary.get("response_latency_p95_ms")


def _compute_failure_flags(trace: SyntheticCallTrace) -> List[str]:
    flags: List[str] = []
    if trace.turn_count == 0:
        flags.append("no_turns")
    if trace.response_latency_p95_ms and trace.response_latency_p95_ms > 3000:
        flags.append("high_latency")
    return flags
