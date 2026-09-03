"""OTLP tracing helpers for in-process playground voice-agent pipelines."""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional

from loguru import logger

from app.services.synthetic_traces.internal_otlp_exporter import InternalOtlpSpanExporter


_mutable_internal_exporter: Optional[InternalOtlpSpanExporter] = None
_correlation_processor: Any = None
_setup_lock = threading.Lock()


def _correlation_span_processor_class():
    from opentelemetry.context import Context
    from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor
    from opentelemetry.sdk.trace import TracerProvider

    class _CorrelationSpanProcessor(SpanProcessor):
        def __init__(self, attributes: Dict[str, str]):
            self._attributes = dict(attributes)

        def update_attributes(self, attributes: Dict[str, str]) -> None:
            self._attributes = dict(attributes)

        def on_start(self, span: Span, parent_context: Optional[Context] = None) -> None:
            for key, value in self._attributes.items():
                span.set_attribute(key, value)

        def on_end(self, span: ReadableSpan) -> None:
            return

        def shutdown(self) -> None:
            return

        def force_flush(self, timeout_millis: int = 30000) -> bool:
            return True

    return _CorrelationSpanProcessor, TracerProvider


def build_pipeline_tracing_kwargs(
    *,
    call_short_id: str,
    workspace_id: str,
    organization_id: str,
    agent_id: Optional[str] = None,
    api_key: Optional[str] = None,
    otlp_endpoint: Optional[str] = None,
) -> Dict[str, Any]:
    """Return PipelineTask kwargs for OTLP export correlated to a trace session."""
    del api_key, otlp_endpoint  # HTTP export superseded by in-process ingest for playground

    if not call_short_id or not workspace_id or not organization_id:
        logger.debug(
            "playground tracing skipped: call_short_id={} workspace_id={} organization_id={}",
            bool(call_short_id),
            bool(workspace_id),
            bool(organization_id),
        )
        return {}

    try:
        from uuid import UUID

        from efficientai.integrations.efficientai_traces.correlation import (
            span_correlation_attributes,
        )
        from efficientai.utils.tracing.setup import is_tracing_available, setup_tracing
        from opentelemetry import trace
    except ImportError:
        logger.warning(
            "OpenTelemetry SDK not installed (pip install efficientai[otel]); "
            "playground pipeline tracing disabled"
        )
        return {}

    if not is_tracing_available():
        logger.warning("OpenTelemetry SDK not installed; playground pipeline tracing disabled")
        return {}

    CorrelationSpanProcessor, TracerProvider = _correlation_span_processor_class()

    org_uuid = UUID(organization_id)
    ws_uuid = UUID(workspace_id)
    attrs = span_correlation_attributes(
        call_short_id=call_short_id,
        agent_id=agent_id,
        workspace_id=workspace_id,
        transport="websocket",
    )

    global _mutable_internal_exporter, _correlation_processor

    with _setup_lock:
        if _mutable_internal_exporter is None:
            _mutable_internal_exporter = InternalOtlpSpanExporter()
            if not setup_tracing("pipecat-agent", exporter=_mutable_internal_exporter):
                logger.warning("Failed to initialize playground tracing exporter")
                _mutable_internal_exporter = None
                return {}

        provider = trace.get_tracer_provider()
        if isinstance(provider, TracerProvider):
            if _correlation_processor is None:
                _correlation_processor = CorrelationSpanProcessor(attrs)
                provider.add_span_processor(_correlation_processor)
            else:
                _correlation_processor.update_attributes(attrs)

        _mutable_internal_exporter.configure(
            organization_id=org_uuid,
            workspace_id=ws_uuid,
            call_short_id=call_short_id,
            agent_id=agent_id,
        )

    logger.info(
        "Playground pipeline tracing enabled for call_short_id={} workspace_id={}",
        call_short_id,
        workspace_id,
    )
    return {
        "enable_tracing": True,
        "additional_span_attributes": attrs,
    }


def flush_playground_tracing() -> None:
    try:
        from efficientai.integrations.efficientai_traces import flush_efficientai_tracing

        flush_efficientai_tracing()
    except ImportError:
        try:
            from efficientai.utils.tracing.setup import flush_tracing

            flush_tracing()
        except ImportError:
            return
    except Exception as exc:
        logger.warning("Failed to flush playground OTLP spans: {}", exc)
