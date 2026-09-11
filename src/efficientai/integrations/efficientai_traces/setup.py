"""OTLP export setup for customer Pipecat pipelines."""

from __future__ import annotations

import os
import threading
from typing import Any, Dict, Mapping, Optional, Sequence

from efficientai.integrations.efficientai_traces.correlation import (
    extract_call_short_id,
    otlp_export_headers,
    span_correlation_attributes,
)
from efficientai.utils.tracing.setup import is_tracing_available, setup_tracing, flush_tracing

try:
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
    from opentelemetry.trace import Span
    from opentelemetry.sdk.trace import ReadableSpan
    from opentelemetry.context import Context
    from opentelemetry.sdk.trace import SpanProcessor

    _OTEL_HTTP_AVAILABLE = True
except ImportError:
    _OTEL_HTTP_AVAILABLE = False
    OTLPSpanExporter = None  # type: ignore
    SpanExporter = object  # type: ignore
    SpanExportResult = object  # type: ignore
    SpanProcessor = object  # type: ignore
    Span = object  # type: ignore
    ReadableSpan = object  # type: ignore
    Context = object  # type: ignore
    TracerProvider = object  # type: ignore

_efficientai_correlation_processor: Optional["_EfficientAICorrelationSpanProcessor"] = None
_mutable_otlp_exporter: Optional["_MutableOtlpExporter"] = None


class _MutableOtlpExporter(SpanExporter):  # type: ignore[misc]
    """OTLP exporter whose HTTP correlation headers update per call."""

    def __init__(self, *, endpoint: str, api_key: str):
        self._endpoint = endpoint
        self._api_key = api_key
        self._call_short_id: Optional[str] = None
        self._evaluator_result_id: Optional[str] = None
        self._inner: Any = None
        self._lock = threading.Lock()

    def configure(
        self,
        *,
        call_short_id: Optional[str] = None,
        evaluator_result_id: Optional[str] = None,
    ) -> None:
        with self._lock:
            self._call_short_id = call_short_id
            self._evaluator_result_id = evaluator_result_id
            self._inner = OTLPSpanExporter(
                endpoint=self._endpoint,
                headers=otlp_export_headers(
                    api_key=self._api_key,
                    call_short_id=call_short_id,
                    evaluator_result_id=evaluator_result_id,
                ),
            )

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        with self._lock:
            if self._inner is None:
                self.configure()
            inner = self._inner
        return inner.export(spans)

    def shutdown(self) -> None:
        with self._lock:
            if self._inner is not None:
                self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        with self._lock:
            if self._inner is None:
                return True
            return bool(self._inner.force_flush(timeout_millis))


class _EfficientAICorrelationSpanProcessor(SpanProcessor):  # type: ignore[misc]
    def __init__(self, attributes: Mapping[str, str]):
        self._attributes = dict(attributes)

    def update_attributes(self, attributes: Mapping[str, str]) -> None:
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


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    val = os.environ.get(name)
    if val is None or not str(val).strip():
        return default
    return str(val).strip()


def _resolve_call_short_id(
    *,
    call_short_id: Optional[str] = None,
    sip_headers: Optional[Mapping[str, Any]] = None,
    webhook_params: Optional[Mapping[str, Any]] = None,
) -> Optional[str]:
    return (
        call_short_id
        or extract_call_short_id(sip_headers=sip_headers, webhook_params=webhook_params)
        or _env("EFFICIENTAI_CALL_SHORT_ID")
    )


def create_otlp_exporter(
    *,
    endpoint: Optional[str] = None,
    api_key: Optional[str] = None,
    call_short_id: Optional[str] = None,
    evaluator_result_id: Optional[str] = None,
    sip_headers: Optional[Mapping[str, Any]] = None,
    webhook_params: Optional[Mapping[str, Any]] = None,
    mutable: bool = True,
) -> Any:
    """Build an OTLP/HTTP exporter pointed at EfficientAI observability traces ingest."""
    if not _OTEL_HTTP_AVAILABLE:
        raise RuntimeError(
            "Install opentelemetry-exporter-otlp-proto-http and opentelemetry-sdk"
        )

    resolved_endpoint = endpoint or _env("EFFICIENTAI_OTLP_ENDPOINT")
    resolved_key = api_key or _env("EFFICIENTAI_API_KEY")
    if not resolved_endpoint:
        raise ValueError("EFFICIENTAI_OTLP_ENDPOINT is required")
    if not resolved_key:
        raise ValueError("EFFICIENTAI_API_KEY is required")

    cid = _resolve_call_short_id(
        call_short_id=call_short_id,
        sip_headers=sip_headers,
        webhook_params=webhook_params,
    )
    run_id = evaluator_result_id or _env("EFFICIENTAI_RUN_ID")

    if mutable:
        global _mutable_otlp_exporter
        if _mutable_otlp_exporter is None:
            _mutable_otlp_exporter = _MutableOtlpExporter(
                endpoint=resolved_endpoint,
                api_key=resolved_key,
            )
        _mutable_otlp_exporter.configure(
            call_short_id=cid,
            evaluator_result_id=run_id,
        )
        return _mutable_otlp_exporter

    return OTLPSpanExporter(
        endpoint=resolved_endpoint,
        headers=otlp_export_headers(
            api_key=resolved_key,
            call_short_id=cid,
            evaluator_result_id=run_id,
        ),
    )


def _attach_correlation_processor(provider: TracerProvider, attrs: Dict[str, str]) -> None:
    global _efficientai_correlation_processor
    if _efficientai_correlation_processor is None:
        _efficientai_correlation_processor = _EfficientAICorrelationSpanProcessor(attrs)
        provider.add_span_processor(_efficientai_correlation_processor)
    else:
        _efficientai_correlation_processor.update_attributes(attrs)


def setup_efficientai_tracing(
    *,
    service_name: str = "pipecat-agent",
    call_short_id: Optional[str] = None,
    evaluator_result_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    transport: Optional[str] = None,
    otlp_endpoint: Optional[str] = None,
    api_key: Optional[str] = None,
    sip_headers: Optional[Mapping[str, Any]] = None,
    webhook_params: Optional[Mapping[str, Any]] = None,
    console_export: bool = False,
) -> bool:
    """
    Configure OpenTelemetry export to EfficientAI for the current process/call.

    Call once per inbound call after reading SIP/webhook metadata.
    """
    if not is_tracing_available():
        return False

    cid = _resolve_call_short_id(
        call_short_id=call_short_id,
        sip_headers=sip_headers,
        webhook_params=webhook_params,
    )
    run_id = evaluator_result_id or _env("EFFICIENTAI_RUN_ID")
    agent = agent_id or _env("EFFICIENTAI_AGENT_ID")
    workspace = workspace_id or _env("EFFICIENTAI_WORKSPACE_ID")
    attrs = span_correlation_attributes(
        call_short_id=cid,
        evaluator_result_id=run_id,
        agent_id=agent,
        workspace_id=workspace,
        transport=transport,
    )

    from opentelemetry import trace

    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        _attach_correlation_processor(provider, attrs)
        exporter = create_otlp_exporter(
            endpoint=otlp_endpoint,
            api_key=api_key,
            call_short_id=cid,
            evaluator_result_id=run_id,
            sip_headers=sip_headers,
            webhook_params=webhook_params,
            mutable=True,
        )
        _ = exporter
        return True

    exporter = create_otlp_exporter(
        endpoint=otlp_endpoint,
        api_key=api_key,
        call_short_id=cid,
        evaluator_result_id=run_id,
        sip_headers=sip_headers,
        webhook_params=webhook_params,
    )
    ok = setup_tracing(service_name, exporter=exporter, console_export=console_export)
    if not ok:
        return False

    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider) and attrs:
        _attach_correlation_processor(provider, attrs)
    return True


def configure_pipecat_tracing(
    *,
    call_short_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    otlp_endpoint: Optional[str] = None,
    api_key: Optional[str] = None,
    sip_headers: Optional[Mapping[str, Any]] = None,
    webhook_params: Optional[Mapping[str, Any]] = None,
    handshake: Optional[Mapping[str, Any]] = None,
    additional_span_attributes: Optional[Dict[str, str]] = None,
    service_name: str = "pipecat-agent",
) -> Dict[str, Any]:
    """
    Configure OTLP export and return kwargs for ``PipelineTask(..., **kwargs)``.

    Example::

        task = PipelineTask(
            pipeline,
            enable_tracing=True,
            **configure_pipecat_tracing(sip_headers=inbound_headers),
        )
    """
    if handshake is not None:
        from efficientai.integrations.efficientai_traces.handshake import (
            configure_pipecat_tracing_from_handshake,
        )

        return configure_pipecat_tracing_from_handshake(
            handshake,
            api_key=api_key,
            service_name=service_name,
        )

    setup_efficientai_tracing(
        service_name=service_name,
        call_short_id=call_short_id,
        agent_id=agent_id,
        workspace_id=workspace_id,
        otlp_endpoint=otlp_endpoint,
        api_key=api_key,
        sip_headers=sip_headers,
        webhook_params=webhook_params,
    )
    cid = _resolve_call_short_id(
        call_short_id=call_short_id,
        sip_headers=sip_headers,
        webhook_params=webhook_params,
    )
    run_id = _env("EFFICIENTAI_RUN_ID")
    agent = agent_id or _env("EFFICIENTAI_AGENT_ID")
    workspace = workspace_id or _env("EFFICIENTAI_WORKSPACE_ID")
    attrs = span_correlation_attributes(
        call_short_id=cid,
        evaluator_result_id=run_id,
        agent_id=agent,
        workspace_id=workspace,
    )
    if additional_span_attributes:
        attrs.update(additional_span_attributes)
    return {
        "enable_tracing": True,
        "additional_span_attributes": attrs,
    }


def flush_efficientai_tracing(timeout_millis: int = 30000) -> bool:
    """Flush pending OTLP spans before closing an EfficientAI trace session."""
    return flush_tracing(timeout_millis)
