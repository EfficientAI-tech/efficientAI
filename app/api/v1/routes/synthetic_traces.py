"""Live call trace observability API (OTLP ingest + read)."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.dependencies import get_api_key, get_db, get_organization_id, get_workspace_id
from app.models.database import EvaluatorResult
from app.models.synthetic_trace_schemas import (
    JsonTraceIngestRequest,
    JsonTraceIngestResponse,
    OtlpIngestResponse,
    OtlpSetupInfo,
    SyntheticCallTraceDetail,
    SyntheticCallTraceListResponse,
    SyntheticCallTraceSummary,
    TraceSessionCloseResponse,
    TraceSessionCreateRequest,
    TraceSessionOtelCorrelation,
    TraceSessionResponse,
    VALID_TRACE_TRANSPORTS,
)
from app.services.synthetic_traces.otlp_ingest import parse_otlp_body
from app.services.synthetic_traces.trace_service import (
    backfill_missing_traces_from_call_recordings,
    build_otlp_setup_info,
    build_session_otel_correlation,
    close_trace_session,
    enrich_trace_summaries,
    get_trace_by_call_short_id,
    get_trace_by_id,
    get_trace_for_result,
    ingest_json_spans,
    ingest_otlp_spans,
    list_traces,
    load_trace_detail,
    open_trace_session,
)

router = APIRouter(prefix="/observability/traces", tags=["observability-traces"])


def _lookup_evaluator_result(
    db: Session,
    id: str,
    organization_id: UUID,
    workspace_id: UUID,
) -> EvaluatorResult | None:
    try:
        result_uuid = UUID(id)
        return (
            db.query(EvaluatorResult)
            .filter(
                EvaluatorResult.id == result_uuid,
                EvaluatorResult.organization_id == organization_id,
                EvaluatorResult.workspace_id == workspace_id,
            )
            .first()
        )
    except ValueError:
        return (
            db.query(EvaluatorResult)
            .filter(
                EvaluatorResult.result_id == id,
                EvaluatorResult.organization_id == organization_id,
                EvaluatorResult.workspace_id == workspace_id,
            )
            .first()
        )


def _api_base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _build_trace_detail_response(db: Session, trace) -> SyntheticCallTraceDetail:
    detail = load_trace_detail(db, trace)
    summary = detail.get("latency_summary") or {}
    base = SyntheticCallTraceSummary.model_validate(trace).model_dump()
    if summary:
        base["turn_count"] = summary.get("turn_count", base.get("turn_count"))
        base["response_latency_sample_count"] = summary.get("response_latency_sample_count")
        base["response_latency_p50_ms"] = summary.get("response_latency_p50_ms")
        base["response_latency_p90_ms"] = summary.get("response_latency_p90_ms")
        base["response_latency_p95_ms"] = summary.get("response_latency_p95_ms")
        base["component_aggregates"] = summary.get("component_aggregates")
    return SyntheticCallTraceDetail(
        **base,
        turns=detail["turns"],
        otel_spans=detail["otel_spans"],
        otel_trace_ids=detail["otel_trace_ids"],
        pipeline_models=detail.get("pipeline_models") or {},
    )


async def _ingest_otlp_traces_handler(
    request: Request,
    db: Session,
    organization_id: UUID,
    workspace_id: UUID,
    x_efficientai_run_id: Optional[str],
    x_efficientai_agent_id: Optional[str],
    x_efficientai_call_short_id: Optional[str],
) -> OtlpIngestResponse:
    body = await request.body()
    if not body:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty OTLP body")

    content_type = request.headers.get("content-type", "")
    try:
        spans, _fmt = parse_otlp_body(body, content_type)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to parse OTLP payload: {exc}",
        ) from exc

    trace, accepted, correlated = ingest_otlp_spans(
        db,
        organization_id=organization_id,
        spans=spans,
        header_evaluator_result_id=x_efficientai_run_id,
        header_agent_id=x_efficientai_agent_id,
        header_call_short_id=x_efficientai_call_short_id,
        workspace_id=workspace_id,
    )
    return OtlpIngestResponse(
        accepted_spans=accepted,
        synthetic_call_trace_id=trace.id if trace else None,
        correlated=correlated,
    )


@router.post("", response_model=OtlpIngestResponse)
async def ingest_observability_traces(
    request: Request,
    db: Session = Depends(get_db),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    x_efficientai_run_id: Optional[str] = Header(None, alias="X-EfficientAI-Run-Id"),
    x_efficientai_agent_id: Optional[str] = Header(None, alias="X-EfficientAI-Agent-Id"),
    x_efficientai_call_short_id: Optional[str] = Header(None, alias="X-EfficientAI-Call-Short-Id"),
):
    """Ingest OTLP spans for a live call (primary export endpoint)."""
    _ = api_key
    return await _ingest_otlp_traces_handler(
        request,
        db,
        organization_id,
        workspace_id,
        x_efficientai_run_id,
        x_efficientai_agent_id,
        x_efficientai_call_short_id,
    )


@router.post("/sessions", response_model=TraceSessionResponse)
def create_trace_session(
    payload: TraceSessionCreateRequest,
    request: Request,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
    api_key: str = Depends(get_api_key),
):
    """Mint call_short_id and open a trace before live audio / OTLP export."""
    _ = api_key
    if payload.transport not in VALID_TRACE_TRANSPORTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"transport must be one of: {', '.join(VALID_TRACE_TRANSPORTS)}",
        )

    if payload.evaluator_result_id:
        result = _lookup_evaluator_result(
            db,
            str(payload.evaluator_result_id),
            organization_id,
            workspace_id,
        )
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Evaluator result not found",
            )

    try:
        trace = open_trace_session(
            db,
            organization_id=organization_id,
            workspace_id=workspace_id,
            evaluator_result_id=payload.evaluator_result_id,
            agent_id=payload.agent_id,
            transport=payload.transport,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    otel = build_session_otel_correlation(
        api_base_url=_api_base_url(request),
        call_short_id=trace.call_short_id or "",
        workspace_id=workspace_id,
        evaluator_result_id=payload.evaluator_result_id,
    )
    return TraceSessionResponse(
        trace_id=trace.id,
        call_short_id=trace.call_short_id or "",
        workspace_id=workspace_id,
        transport=trace.transport,
        status=trace.status,
        otel_correlation=TraceSessionOtelCorrelation(**otel),
    )


@router.post("/sessions/{call_short_id}/close", response_model=TraceSessionCloseResponse)
def close_trace_session_route(
    call_short_id: str,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
    api_key: str = Depends(get_api_key),
):
    _ = api_key
    trace = close_trace_session(
        db,
        organization_id=organization_id,
        call_short_id=call_short_id,
        workspace_id=workspace_id,
    )
    if not trace:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trace session not found")
    return TraceSessionCloseResponse(
        trace_id=trace.id,
        call_short_id=call_short_id,
        status=trace.status,
    )


@router.post("/ingest", response_model=JsonTraceIngestResponse, deprecated=True)
def ingest_json_traces(
    payload: JsonTraceIngestRequest,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
    api_key: str = Depends(get_api_key),
):
    """Deprecated: prefer OTLP export. Simple JSON shim for non-OTel prototypes only."""
    _ = api_key
    if not payload.spans:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="spans required")

    span_dicts = [s.model_dump() for s in payload.spans]
    trace, accepted, correlated = ingest_json_spans(
        db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        call_short_id=payload.call_short_id,
        spans=span_dicts,
    )
    return JsonTraceIngestResponse(
        accepted_spans=accepted,
        synthetic_call_trace_id=trace.id if trace else None,
        correlated=correlated,
    )


@router.get("/setup", response_model=OtlpSetupInfo)
def get_otlp_setup(
    request: Request,
    api_key: str = Depends(get_api_key),
):
    """One-time OTLP endpoint + Pipecat config."""
    _ = api_key
    return OtlpSetupInfo(**build_otlp_setup_info(api_base_url=_api_base_url(request)))


@router.get("", response_model=SyntheticCallTraceListResponse)
def list_observability_traces(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status: Optional[str] = Query(None, description="open or closed"),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
    api_key: str = Depends(get_api_key),
):
    _ = api_key
    rows, total = list_traces(
        db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        skip=skip,
        limit=limit,
        status=status,
    )
    items = enrich_trace_summaries(db, rows)
    return SyntheticCallTraceListResponse(
        items=[SyntheticCallTraceSummary.model_validate(item) for item in items],
        total=total,
    )


@router.get("/results/{evaluator_result_id}", response_model=SyntheticCallTraceDetail)
def get_trace_for_evaluator_result(
    evaluator_result_id: str,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
    api_key: str = Depends(get_api_key),
):
    _ = api_key
    result = _lookup_evaluator_result(
        db, evaluator_result_id, organization_id, workspace_id
    )
    if not result:
        raise HTTPException(status_code=404, detail="Evaluator result not found")

    backfill_missing_traces_from_call_recordings(
        db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        limit=5,
    )

    trace = get_trace_for_result(
        db,
        organization_id=organization_id,
        evaluator_result_id=result.id,
        workspace_id=workspace_id,
    )
    if not trace and result.synthetic_call_trace_id:
        trace = get_trace_by_id(
            db,
            organization_id=organization_id,
            trace_id=result.synthetic_call_trace_id,
            workspace_id=workspace_id,
        )
    if not trace:
        raise HTTPException(status_code=404, detail="Call trace not found")

    return _build_trace_detail_response(db, trace)


@router.get("/by-call-short-id/{call_short_id}", response_model=SyntheticCallTraceDetail)
def get_trace_by_call_short_id_route(
    call_short_id: str,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
    api_key: str = Depends(get_api_key),
):
    _ = api_key
    trace = get_trace_by_call_short_id(
        db,
        organization_id=organization_id,
        call_short_id=call_short_id,
        workspace_id=workspace_id,
    )
    if not trace:
        raise HTTPException(status_code=404, detail="Call trace not found")
    return _build_trace_detail_response(db, trace)


@router.get("/{trace_id}", response_model=SyntheticCallTraceDetail)
def get_observability_trace(
    trace_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
    api_key: str = Depends(get_api_key),
):
    _ = api_key
    trace = get_trace_by_id(
        db,
        organization_id=organization_id,
        trace_id=trace_id,
        workspace_id=workspace_id,
    )
    if not trace:
        raise HTTPException(status_code=404, detail="Call trace not found")
    return _build_trace_detail_response(db, trace)
