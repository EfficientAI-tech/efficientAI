"""Pydantic schemas for synthetic call traces."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SyntheticTraceTurn(BaseModel):
    turn_number: int
    sut_response_latency_ms: Optional[float] = None
    caller_stream_complete_at: Optional[float] = None
    sut_speech_start_at: Optional[float] = None
    sut_speech_stop_at: Optional[float] = None
    talk_over: bool = False
    stt_ttfb_ms: Optional[float] = None
    llm_ttfb_ms: Optional[float] = None
    tts_ttfb_ms: Optional[float] = None
    s2s_ttfb_ms: Optional[float] = None
    transcript: Optional[str] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class OtelSpanRecord(BaseModel):
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    name: str
    start_time_unix_nano: Optional[int] = None
    end_time_unix_nano: Optional[int] = None
    attributes: Dict[str, Any] = Field(default_factory=dict)
    events: List[Dict[str, Any]] = Field(default_factory=list)


class SyntheticCallTraceSummary(BaseModel):
    id: UUID
    evaluator_result_id: Optional[UUID] = None
    agent_id: Optional[UUID] = None
    call_short_id: Optional[str] = None
    environment: str
    transport: str
    tier: str
    status: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    turn_count: int = 0
    response_latency_p50_ms: Optional[float] = None
    response_latency_p90_ms: Optional[float] = None
    response_latency_p95_ms: Optional[float] = None
    component_aggregates: Optional[Dict[str, Any]] = None
    failure_flags: Optional[List[str]] = None
    call_recording_id: Optional[UUID] = None

    model_config = ConfigDict(from_attributes=True)


class SyntheticCallTraceDetail(SyntheticCallTraceSummary):
    turns: List[SyntheticTraceTurn] = Field(default_factory=list)
    otel_spans: List[OtelSpanRecord] = Field(default_factory=list)
    otel_trace_ids: List[str] = Field(default_factory=list)
    pipeline_models: Dict[str, Dict[str, Optional[str]]] = Field(default_factory=dict)


class OtelCorrelationInfo(BaseModel):
    evaluator_result_id: UUID
    synthetic_call_trace_id: Optional[UUID] = None
    call_short_id: Optional[str] = None
    agent_id: Optional[UUID] = None
    otlp_endpoint: str
    suggested_env_vars: Dict[str, str] = Field(default_factory=dict)
    suggested_span_attributes: Dict[str, str] = Field(default_factory=dict)


class OtlpIngestResponse(BaseModel):
    accepted_spans: int
    synthetic_call_trace_id: Optional[UUID] = None
    correlated: bool = False


class SyntheticCallTraceListResponse(BaseModel):
    items: List[SyntheticCallTraceSummary]
    total: int


class OtlpSetupInfo(BaseModel):
    """Pipecat WebRTC local setup for call trace ingest."""

    otlp_endpoint: str
    sessions_endpoint: str = ""
    api_key_header: str = "X-API-Key"
    workspace_header: str = "X-Workspace-Id"
    one_time_env_vars: Dict[str, str] = Field(default_factory=dict)
    setup_steps: List[Dict[str, str]] = Field(default_factory=list)
    transport_options: Dict[str, str] = Field(default_factory=dict)
    per_call_correlation: Dict[str, str] = Field(default_factory=dict)
    suggested_span_resource_attributes: Dict[str, str] = Field(default_factory=dict)
    pipecat_python_example: str = ""


VALID_TRACE_TRANSPORTS = ("webrtc", "websocket", "phone", "custom")


class TraceSessionCreateRequest(BaseModel):
    evaluator_result_id: Optional[UUID] = None
    agent_id: Optional[UUID] = None
    transport: str = "websocket"


class TraceSessionOtelCorrelation(BaseModel):
    otlp_endpoint: str
    api_key_header: str = "X-API-Key"
    suggested_env_vars: Dict[str, str] = Field(default_factory=dict)
    suggested_otlp_headers: Dict[str, str] = Field(default_factory=dict)
    suggested_span_attributes: Dict[str, str] = Field(default_factory=dict)


class TraceSessionResponse(BaseModel):
    trace_id: UUID
    call_short_id: str
    workspace_id: UUID
    transport: str
    status: str
    otel_correlation: TraceSessionOtelCorrelation


class TraceSessionCloseResponse(BaseModel):
    trace_id: UUID
    call_short_id: str
    status: str


class JsonTraceSpanInput(BaseModel):
    name: str
    turn_number: int
    ttfb_ms: Optional[float] = None
    attributes: Dict[str, Any] = Field(default_factory=dict)


class JsonTraceIngestRequest(BaseModel):
    call_short_id: str
    spans: List[JsonTraceSpanInput] = Field(default_factory=list)


class JsonTraceIngestResponse(BaseModel):
    accepted_spans: int
    synthetic_call_trace_id: Optional[UUID] = None
    correlated: bool = False
