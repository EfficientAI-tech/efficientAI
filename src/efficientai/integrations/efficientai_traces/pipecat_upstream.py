"""Moved to :mod:`efficientai_sdk.tracing.session` and :mod:`efficientai_sdk.integrations.pipecat`.
Kept so existing imports keep working."""

from efficientai_sdk.integrations.pipecat import setup_pipecat_worker_tracing
from efficientai_sdk.tracing.session import (
    DEFAULT_OTLP_PATH,
    TraceSessionError,
    close_trace_session,
    ensure_trace_session,
    mint_trace_session,
    missing_deployment_trace_env,
    require_deployment_trace_env,
    resolve_trace_transport,
    trace_session_enabled,
    warn_deployment_trace_env,
)

__all__ = [
    "DEFAULT_OTLP_PATH",
    "TraceSessionError",
    "close_trace_session",
    "ensure_trace_session",
    "mint_trace_session",
    "missing_deployment_trace_env",
    "require_deployment_trace_env",
    "resolve_trace_transport",
    "setup_pipecat_worker_tracing",
    "trace_session_enabled",
    "warn_deployment_trace_env",
]
