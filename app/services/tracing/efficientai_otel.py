"""EfficientAI OpenTelemetry bootstrap helpers."""

from __future__ import annotations

import os
from typing import Dict, Optional

from loguru import logger

from app.config import settings

try:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

    OTEL_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    OTEL_AVAILABLE = False


_INITIALIZED = False


def _normalized_sample_rate() -> float:
    try:
        value = float(settings.OBSERVABILITY_TRACING_SAMPLE_RATE)
    except (TypeError, ValueError):
        logger.warning(
            "Invalid OBSERVABILITY_TRACING_SAMPLE_RATE {!r}; using 1.0",
            settings.OBSERVABILITY_TRACING_SAMPLE_RATE,
        )
        return 1.0
    if value < 0.0 or value > 1.0:
        logger.warning("OBSERVABILITY_TRACING_SAMPLE_RATE out of range {}; clamping to [0,1]", value)
        return min(1.0, max(0.0, value))
    return value


def _build_headers() -> Dict[str, str]:
    api_key = settings.EFFICIENT_AI_API_KEY or os.getenv("EFFICIENT_AI_API_KEY")
    agent_id = settings.EFFICIENT_AI_AGENT_ID or os.getenv("EFFICIENT_AI_AGENT_ID")
    project_id = settings.EFFICIENT_AI_PROJECT_ID or os.getenv("EFFICIENT_AI_PROJECT_ID")

    headers: Dict[str, str] = {}
    if api_key:
        headers["x-efficient-ai-api-key"] = api_key
    if agent_id:
        headers["x-efficient-ai-agent-id"] = agent_id
    elif project_id:
        headers["x-efficient-ai-project-id"] = project_id
    return headers


def _get_or_create_provider(service_name: str) -> Optional["TracerProvider"]:
    if not OTEL_AVAILABLE:
        return None

    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        return provider

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.instance.id": os.getenv("HOSTNAME", "unknown"),
            "deployment.environment": os.getenv("ENVIRONMENT", "development"),
        }
    )
    sample_rate = _normalized_sample_rate()
    provider = TracerProvider(
        resource=resource,
        sampler=ParentBased(root=TraceIdRatioBased(sample_rate)),
    )
    trace.set_tracer_provider(provider)
    return provider


def setup_efficientai_tracing(service_name: str = "efficientai-voice-agent") -> bool:
    """Initialize tracing once per process; safe to call repeatedly."""
    global _INITIALIZED
    if _INITIALIZED:
        return True
    if not OTEL_AVAILABLE:
        logger.warning("OpenTelemetry not available; tracing disabled")
        return False
    if not settings.OBSERVABILITY_TRACING_ENABLED:
        return False

    provider = _get_or_create_provider(service_name)
    if provider is None:
        return False

    exporter_mode = (settings.OBSERVABILITY_TRACING_EXPORTER or "efficientai_http").strip().lower()
    endpoint = settings.OTEL_EXPORTER_OTLP_ENDPOINT
    headers = _build_headers()

    try:
        if exporter_mode == "console":
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        elif exporter_mode in {"efficientai_http", "tempo_http"}:
            if not endpoint:
                logger.warning("Tracing enabled but OTLP endpoint is empty")
                return False
            if "x-efficient-ai-api-key" not in headers and exporter_mode == "efficientai_http":
                logger.warning("Tracing enabled but EFFICIENT_AI_API_KEY missing")
                return False
            exporter = OTLPSpanExporter(endpoint=endpoint, headers=headers)
            provider.add_span_processor(BatchSpanProcessor(exporter))
        else:
            logger.warning("Unsupported tracing exporter: {}", exporter_mode)
            return False
    except Exception as exc:
        logger.warning("Failed to initialize tracing exporter: {}", exc)
        return False

    _INITIALIZED = True
    logger.info("Tracing initialized with exporter={}", exporter_mode)
    return True


def force_flush_tracing(timeout_millis: int = 3000) -> None:
    """Flush active span processors; best-effort no-op when unavailable."""
    if not OTEL_AVAILABLE:
        return
    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        try:
            provider.force_flush(timeout_millis=timeout_millis)
        except Exception as exc:  # pragma: no cover
            logger.debug("Tracing force_flush failed: {}", exc)


def log_trace_export_status(trace_id: Optional[str]) -> None:
    """Best-effort check that exported spans are queryable in the configured backend."""
    if not trace_id or not settings.OBSERVABILITY_TRACING_ENABLED:
        return
    backend = (settings.TRACING_QUERY_BACKEND or "cloud").strip().lower()
    if backend != "tempo":
        return
    try:
        import httpx

        base = settings.TEMPO_QUERY_URL.rstrip("/")
        response = httpx.get(f"{base}/api/traces/{trace_id}", timeout=3.0)
        if response.status_code == 404:
            logger.warning(
                "Trace {} was linked to the call but Tempo has no spans yet. "
                "Check OTLP export to {} and Tempo retention.",
                trace_id,
                settings.OTEL_EXPORTER_OTLP_ENDPOINT,
            )
        elif response.is_success:
            logger.info("Trace {} confirmed in Tempo", trace_id)
    except Exception as exc:
        logger.warning(
            "Could not verify trace {} in Tempo at {}: {}",
            trace_id,
            settings.TEMPO_QUERY_URL,
            exc,
        )
