"""ClickHouse-backed trace operations (S3 WAL serving path)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.config import settings
from app.models.database import Agent, EvaluatorResult
from app.models.synthetic_trace_schemas import VALID_TRACE_TRANSPORTS
from app.services.clickhouse.client import clickhouse_enabled
from app.services.synthetic_traces.clickhouse_store import (
    TraceRecord,
    _resolve_otel_trace_id,
    get_live_turns,
    get_observations,
    get_trace_by_evaluator_result_id,
    get_trace_by_id,
    get_trace_by_uuid,
    insert_observations,
    list_idle_open_traces,
    mint_trace_uuid,
    set_live_turns,
    upsert_trace_header,
)
from app.services.synthetic_traces.otlp_mapper import (
    annotate_spans_with_display_turn,
    compute_component_aggregates,
    compute_trace_latency_summary,
    derive_turns_from_spans,
    extract_pipeline_models,
    filter_spans_for_trace,
    merge_tier1_and_otel_turns,
    spans_indicate_session_end,
)
from app.services.synthetic_traces.span_storage import SPANS_STORAGE_S3, collect_trace_ids
from app.utils.call_recordings import generate_unique_call_short_id

TraceLike = Union[TraceRecord, Any]


def use_ch() -> bool:
    return clickhouse_enabled()


def _utcnow():
    from app.services.synthetic_traces.trace_service import _utcnow as utc

    return utc()


def _link_evaluator_result(db: Session, trace: TraceRecord) -> None:
    if not trace.evaluator_result_id:
        return
    result = (
        db.query(EvaluatorResult)
        .filter(EvaluatorResult.id == trace.evaluator_result_id)
        .first()
    )
    if result:
        result.synthetic_call_trace_id = trace.id
        db.commit()


def open_trace_ch(
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
) -> TraceRecord:
    if evaluator_result_id:
        existing = get_trace_by_evaluator_result_id(
            organization_id=organization_id,
            evaluator_result_id=evaluator_result_id,
            workspace_id=workspace_id,
        )
        if existing and existing.status == "open":
            return existing
        result = (
            db.query(EvaluatorResult)
            .filter(EvaluatorResult.id == evaluator_result_id)
            .first()
        )
        if result and result.synthetic_call_trace_id:
            found = get_trace_by_uuid(result.synthetic_call_trace_id)
            if found and found.status == "open":
                return found

    trace = TraceRecord(
        id=mint_trace_uuid(),
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
        spans_storage="clickhouse",
    )
    upsert_trace_header(trace)
    _link_evaluator_result(db, trace)
    return trace


def open_trace_session_ch(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    agent_id: Optional[UUID] = None,
    evaluator_result_id: Optional[UUID] = None,
    transport: str = "websocket",
    call_short_id: Optional[str] = None,
) -> TraceRecord:
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
    persona_id = scenario_id = evaluator_id = None
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

    return open_trace_ch(
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


def _derive_turns_for_trace(trace: TraceRecord, spans: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    scoped = filter_spans_for_trace(spans, call_short_id=trace.call_short_id)
    stored_turns = list(trace.turns or [])
    tier1_turns = []
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
    otel_turns = derive_turns_from_spans(scoped)
    if scoped:
        return merge_tier1_and_otel_turns(tier1_turns, otel_turns)
    return stored_turns


def apply_derived_to_trace(trace: TraceRecord, scoped_spans: List[Dict[str, Any]]) -> TraceRecord:
    turns = _derive_turns_for_trace(trace, scoped_spans)
    summary = compute_trace_latency_summary(turns) if turns else {}
    trace.turns = turns
    trace.turn_count = len(turns)
    trace.component_aggregates = compute_component_aggregates(turns)
    if summary.get("response_latency_p50_ms") is not None:
        trace.response_latency_p50_ms = summary["response_latency_p50_ms"]
        trace.response_latency_p90_ms = summary.get("response_latency_p90_ms")
        trace.response_latency_p95_ms = summary.get("response_latency_p95_ms")
    trace.derive_pending = False
    trace.last_span_at = _utcnow()
    upsert_trace_header(trace)
    set_live_turns(trace.id, turns)
    return trace


def derive_trace_turns_ch(db: Session, *, trace_id: UUID) -> Optional[TraceRecord]:
    trace = get_trace_by_uuid(trace_id)
    if not trace:
        return None

    spans = get_observations(trace_id)
    scoped = filter_spans_for_trace(spans, call_short_id=trace.call_short_id)
    trace = apply_derived_to_trace(trace, scoped)

    from app.workers.tasks.trace_tasks import close_and_offload_trace_task

    if scoped and spans_indicate_session_end(scoped):
        close_and_offload_trace_task.delay(str(trace.id))
    return trace


def close_trace_session_ch(
    db: Session,
    *,
    organization_id: UUID,
    call_short_id: str,
    workspace_id: Optional[UUID] = None,
) -> Optional[TraceRecord]:
    from app.services.synthetic_traces.clickhouse_store import get_trace_by_call_short_id

    trace = get_trace_by_call_short_id(
        organization_id=organization_id,
        call_short_id=call_short_id,
        workspace_id=workspace_id,
    )
    if not trace:
        return None
    if trace.status in ("closed", "finalized"):
        return trace
    if settings.TRACES_ASYNC_INGEST_ENABLED:
        from app.workers.tasks.trace_tasks import close_and_offload_trace_task

        try:
            close_and_offload_trace_task.delay(str(trace.id))
        except Exception as exc:
            logger.debug("Celery unavailable for close; running inline: {}", exc)
            return close_and_offload_trace_ch(db, trace_id=trace.id)
        trace.status = "closing"
        upsert_trace_header(trace)
        return trace
    return close_and_offload_trace_ch(db, trace_id=trace.id)


def close_and_offload_trace_ch(db: Session, *, trace_id: UUID) -> Optional[TraceRecord]:
    trace = get_trace_by_uuid(trace_id)
    if not trace:
        return None

    spans = get_observations(trace_id)
    scoped = filter_spans_for_trace(spans, call_short_id=trace.call_short_id)
    trace = apply_derived_to_trace(trace, scoped)

    from app.services.synthetic_traces.span_storage import upload_trace_spans_to_s3_ch

    s3_key = upload_trace_spans_to_s3_ch(trace, scoped)
    if s3_key:
        trace.spans_s3_key = s3_key
        trace.spans_storage = SPANS_STORAGE_S3

    trace.status = "closed"
    trace.ended_at = _utcnow()
    flags: List[str] = []
    if trace.turn_count == 0:
        flags.append("no_turns")
    if trace.response_latency_p95_ms and trace.response_latency_p95_ms > 3000:
        flags.append("high_latency")
    trace.failure_flags = flags
    trace.derive_pending = False
    upsert_trace_header(trace)
    return trace


def sweep_idle_traces_ch(db: Session) -> int:
    idle_seconds = max(1, int(settings.TRACES_IDLE_CLOSE_SECONDS))
    cutoff = _utcnow() - timedelta(seconds=idle_seconds)
    rows = list_idle_open_traces(cutoff)
    from app.workers.tasks.trace_tasks import close_and_offload_trace_task

    for trace in rows:
        close_and_offload_trace_task.delay(str(trace.id))
    return len(rows)


def _hydrate_span_trace_ids(
    spans: List[Dict[str, Any]],
    fallback_trace_id: str,
) -> List[Dict[str, Any]]:
    for span in spans:
        if span.get("trace_id"):
            continue
        attrs = span.get("attributes") or {}
        span["trace_id"] = _resolve_otel_trace_id(None, attrs, fallback_trace_id)
    return spans


def load_trace_detail_ch(
    trace: TraceRecord,
    *,
    include_spans: bool = True,
) -> Dict[str, Any]:
    live_turns = get_live_turns(trace.id)
    turns = live_turns if live_turns is not None else (trace.turns or [])
    spans = get_observations(trace.id)
    scoped_spans = filter_spans_for_trace(spans, call_short_id=trace.call_short_id)
    scoped_spans = _hydrate_span_trace_ids(scoped_spans, trace.id.hex)
    if not turns and scoped_spans:
        turns = _derive_turns_for_trace(trace, scoped_spans)
    annotated_spans = (
        annotate_spans_with_display_turn(scoped_spans, precomputed_turns=turns)
        if scoped_spans
        else []
    )
    otel_spans = annotated_spans if include_spans else []
    latency_summary = compute_trace_latency_summary(turns) if turns else {}
    trace_ids = collect_trace_ids(scoped_spans) if scoped_spans else []
    return {
        "trace": trace,
        "turns": turns,
        "otel_spans": otel_spans,
        "otel_trace_ids": trace_ids,
        "latency_summary": latency_summary,
        "pipeline_models": extract_pipeline_models(annotated_spans),
    }


def load_trace_spans_only_ch(trace: TraceRecord) -> Dict[str, Any]:
    detail = load_trace_detail_ch(trace, include_spans=True)
    return {
        "otel_spans": detail["otel_spans"],
        "otel_trace_ids": detail["otel_trace_ids"],
        "spans_storage": trace.spans_storage,
    }


def persist_spans_ch(
    trace: TraceRecord,
    spans: List[Dict[str, Any]],
) -> TraceRecord:
    insert_observations(workspace_id=trace.workspace_id, trace_uuid=trace.id, spans=spans)
    trace.span_count = int(trace.span_count or 0) + len(spans)
    trace.last_span_at = _utcnow()
    trace.derive_pending = True
    upsert_trace_header(trace)
    return trace
