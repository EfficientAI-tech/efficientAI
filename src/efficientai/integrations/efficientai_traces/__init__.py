"""EfficientAI synthetic trace helpers for self-hosted Pipecat agents."""

from efficientai.integrations.efficientai_traces.correlation import (
    build_outbound_sip_headers,
    extract_call_short_id,
    otlp_export_headers,
    span_correlation_attributes,
)
from efficientai.integrations.efficientai_traces.handshake import (
    HANDSHAKE_TYPE,
    configure_pipecat_tracing_from_handshake,
    parse_trace_handshake,
)
from efficientai.integrations.efficientai_traces.pipecat_upstream import (
    close_trace_session,
    ensure_trace_session,
    mint_trace_session,
    missing_deployment_trace_env,
    require_deployment_trace_env,
    resolve_trace_transport,
    setup_pipecat_worker_tracing,
)
from efficientai.integrations.efficientai_traces.setup import (
    configure_pipecat_tracing,
    create_otlp_exporter,
    flush_efficientai_tracing,
    setup_efficientai_tracing,
)

__all__ = [
    "HANDSHAKE_TYPE",
    "build_outbound_sip_headers",
    "close_trace_session",
    "configure_pipecat_tracing",
    "configure_pipecat_tracing_from_handshake",
    "create_otlp_exporter",
    "flush_efficientai_tracing",
    "ensure_trace_session",
    "extract_call_short_id",
    "mint_trace_session",
    "missing_deployment_trace_env",
    "otlp_export_headers",
    "parse_trace_handshake",
    "require_deployment_trace_env",
    "resolve_trace_transport",
    "setup_efficientai_tracing",
    "setup_pipecat_worker_tracing",
    "span_correlation_attributes",
]
