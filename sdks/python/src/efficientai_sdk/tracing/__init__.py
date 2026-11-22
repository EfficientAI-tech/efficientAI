"""Live call tracing: send OpenTelemetry spans from your agent to EfficientAI.

Install with the ``otel`` extra to export spans::

    pip install "efficientai-sdk[otel]"

Correlation and handshake helpers work without it.
"""

from efficientai_sdk.tracing.api import (
    AsyncTraceResource,
    CallTrace,
    ComponentSpan,
    TraceResource,
    TurnSpan,
)
from efficientai_sdk.tracing.context import call_attributes, get_call_attributes
from efficientai_sdk.tracing.correlation import (
    ATTR_AGENT_ID,
    ATTR_CALL_SHORT_ID,
    ATTR_ENVIRONMENT,
    ATTR_ORGANIZATION_ID,
    ATTR_RUN_ID,
    ATTR_TRANSPORT,
    ATTR_WORKSPACE_ID,
    OTLP_HEADER_API_KEY,
    OTLP_HEADER_CALL_SHORT_ID,
    OTLP_HEADER_RUN_ID,
    OTLP_HEADER_WORKSPACE_ID,
    build_outbound_sip_headers,
    extract_call_short_id,
    format_plivo_sip_headers,
    otlp_export_headers,
    span_correlation_attributes,
)
from efficientai_sdk.tracing.handshake import HANDSHAKE_TYPE, parse_trace_handshake
from efficientai_sdk.tracing.otel import (
    OTEL_AVAILABLE,
    create_otlp_exporter,
    ensure_export_pipeline,
    flush_efficientai_tracing,
    is_tracing_available,
    setup_efficientai_tracing,
    setup_tracer_provider,
)
from efficientai_sdk.tracing.session import (
    DEFAULT_OTLP_PATH,
    TraceSessionError,
    close_trace_session,
    ensure_trace_session,
    mint_trace_session,
    missing_deployment_trace_env,
    require_deployment_trace_env,
    resolve_otlp_endpoint,
    resolve_trace_transport,
    setup_worker_tracing,
    trace_session_enabled,
    warn_deployment_trace_env,
)

__all__ = [
    "ATTR_AGENT_ID",
    "ATTR_CALL_SHORT_ID",
    "ATTR_ENVIRONMENT",
    "ATTR_ORGANIZATION_ID",
    "ATTR_RUN_ID",
    "ATTR_TRANSPORT",
    "ATTR_WORKSPACE_ID",
    "DEFAULT_OTLP_PATH",
    "HANDSHAKE_TYPE",
    "OTEL_AVAILABLE",
    "OTLP_HEADER_API_KEY",
    "OTLP_HEADER_CALL_SHORT_ID",
    "OTLP_HEADER_RUN_ID",
    "OTLP_HEADER_WORKSPACE_ID",
    "AsyncTraceResource",
    "CallTrace",
    "ComponentSpan",
    "TraceResource",
    "TraceSessionError",
    "TurnSpan",
    "build_outbound_sip_headers",
    "call_attributes",
    "close_trace_session",
    "create_otlp_exporter",
    "ensure_export_pipeline",
    "ensure_trace_session",
    "extract_call_short_id",
    "flush_efficientai_tracing",
    "format_plivo_sip_headers",
    "get_call_attributes",
    "is_tracing_available",
    "mint_trace_session",
    "missing_deployment_trace_env",
    "otlp_export_headers",
    "parse_trace_handshake",
    "require_deployment_trace_env",
    "resolve_otlp_endpoint",
    "resolve_trace_transport",
    "setup_efficientai_tracing",
    "setup_tracer_provider",
    "setup_worker_tracing",
    "span_correlation_attributes",
    "trace_session_enabled",
    "warn_deployment_trace_env",
]
