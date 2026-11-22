"""OpenTelemetry export to EfficientAI. Needs the ``otel`` extra:

    pip install "efficientai-sdk[otel]"

Importing this module without OpenTelemetry installed is safe; the setup functions
then return ``False`` (or raise, for :func:`create_otlp_exporter`).
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Optional

from efficientai_sdk.tracing.context import get_call_attributes, set_call_attributes
from efficientai_sdk.tracing.correlation import (
    ATTR_CALL_SHORT_ID,
    extract_call_short_id,
    otlp_export_headers,
    span_correlation_attributes,
)

logger = logging.getLogger("efficientai_sdk.tracing")

try:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor, TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
        SpanExporter,
        SpanExportResult,
    )

    OTEL_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without the extra
    OTEL_AVAILABLE = False
    if not TYPE_CHECKING:
        SpanExporter = object
        SpanProcessor = object
        TracerProvider = None

if TYPE_CHECKING:
    from opentelemetry.context import Context
    from opentelemetry.trace import Span

__all__ = [
    "OTEL_AVAILABLE",
    "create_otlp_exporter",
    "ensure_export_pipeline",
    "flush_efficientai_tracing",
    "is_tracing_available",
    "setup_efficientai_tracing",
    "setup_tracer_provider",
]

_OTEL_MISSING = (
    "OpenTelemetry is not installed. Install the extra: pip install 'efficientai-sdk[otel]'"
)

_state_lock = threading.Lock()
_correlation_processor: Optional[_CorrelationSpanProcessor] = None
_mutable_exporter: Optional[_MutableOtlpExporter] = None
_exporter_attached = False
# Export pipelines added by ensure_export_pipeline, keyed by (endpoint, api_key, workspace).
_pipelines: dict[tuple[str, str, Optional[str]], Any] = {}


def is_tracing_available() -> bool:
    return OTEL_AVAILABLE


def _env(name: str) -> Optional[str]:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    return value.strip()


class _MutableOtlpExporter(SpanExporter):
    """OTLP exporter whose correlation headers can be switched per call.

    One instance is attached to the tracer provider for the life of the process; each
    new call reconfigures the headers instead of adding another span processor.
    """

    def __init__(self, *, endpoint: str, api_key: str) -> None:
        self._endpoint = endpoint
        self._api_key = api_key
        self._inner: Any = None
        self._lock = threading.Lock()

    @property
    def endpoint(self) -> str:
        return self._endpoint

    def configure(
        self,
        *,
        call_short_id: Optional[str] = None,
        evaluator_result_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> None:
        inner = OTLPSpanExporter(
            endpoint=self._endpoint,
            headers=otlp_export_headers(
                api_key=self._api_key,
                call_short_id=call_short_id,
                evaluator_result_id=evaluator_result_id,
                workspace_id=workspace_id,
            ),
        )
        with self._lock:
            self._inner = inner

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        with self._lock:
            if self._inner is None:
                self._inner = OTLPSpanExporter(
                    endpoint=self._endpoint,
                    headers=otlp_export_headers(api_key=self._api_key),
                )
            inner = self._inner
        result: SpanExportResult = inner.export(spans)
        return result

    def shutdown(self) -> None:
        with self._lock:
            if self._inner is not None:
                self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        with self._lock:
            inner = self._inner
        return True if inner is None else bool(inner.force_flush(timeout_millis))


_EFFICIENTAI_PREFIX = "efficientai."


def _parent_call_attributes(parent_context: Optional[Context]) -> Optional[dict[str, str]]:
    """``efficientai.*`` attributes of the parent span, when it belongs to a call."""
    parent = trace.get_current_span(parent_context)
    attrs = getattr(parent, "attributes", None)
    if not attrs or ATTR_CALL_SHORT_ID not in attrs:
        return None
    return {k: str(v) for k, v in attrs.items() if k.startswith(_EFFICIENTAI_PREFIX)}


class _CorrelationSpanProcessor(SpanProcessor):
    """Stamps EfficientAI correlation attributes on every span when it starts.

    Source, in order: the call active in the current context, the parent span's call,
    then the process-wide default set by :func:`setup_efficientai_tracing`. Attributes
    already set on the span (for example by the SDK's own span helpers) are kept.
    """

    def __init__(self, attributes: Mapping[str, str]) -> None:
        self._attributes = dict(attributes)
        self.active = True

    def update_attributes(self, attributes: Mapping[str, str]) -> None:
        self._attributes = dict(attributes)

    def on_start(self, span: Span, parent_context: Optional[Context] = None) -> None:
        if not self.active:
            return
        attrs = get_call_attributes() or _parent_call_attributes(parent_context) or self._attributes
        if not attrs:
            return
        existing = getattr(span, "attributes", None) or {}
        for key, value in attrs.items():
            if key not in existing:
                span.set_attribute(key, value)

    def on_end(self, span: ReadableSpan) -> None:
        return

    def shutdown(self) -> None:
        return

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


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
    workspace_id: Optional[str] = None,
    sip_headers: Optional[Mapping[str, Any]] = None,
    webhook_params: Optional[Mapping[str, Any]] = None,
    mutable: bool = True,
) -> Any:
    """Build an OTLP/HTTP span exporter pointed at EfficientAI trace ingest.

    With ``mutable=True`` (default) a single process-wide exporter is reused and its
    correlation headers are updated for the new call. Its endpoint and API key are
    fixed by the first call.
    """
    global _mutable_exporter
    if not OTEL_AVAILABLE:
        raise RuntimeError(_OTEL_MISSING)

    resolved_endpoint = endpoint or _env("EFFICIENTAI_OTLP_ENDPOINT")
    resolved_key = api_key or _env("EFFICIENTAI_API_KEY")
    if not resolved_endpoint:
        raise ValueError("EFFICIENTAI_OTLP_ENDPOINT is required")
    if not resolved_key:
        raise ValueError("EFFICIENTAI_API_KEY is required")

    cid = _resolve_call_short_id(
        call_short_id=call_short_id, sip_headers=sip_headers, webhook_params=webhook_params
    )
    run_id = evaluator_result_id or _env("EFFICIENTAI_RUN_ID")
    workspace = workspace_id or _env("EFFICIENTAI_WORKSPACE_ID")

    if not mutable:
        return OTLPSpanExporter(
            endpoint=resolved_endpoint,
            headers=otlp_export_headers(
                api_key=resolved_key,
                call_short_id=cid,
                evaluator_result_id=run_id,
                workspace_id=workspace,
            ),
        )

    with _state_lock:
        if _mutable_exporter is None:
            _mutable_exporter = _MutableOtlpExporter(
                endpoint=resolved_endpoint, api_key=resolved_key
            )
        elif _mutable_exporter.endpoint != resolved_endpoint:
            logger.warning(
                "EfficientAI OTLP exporter already targets %s; ignoring new endpoint %s",
                _mutable_exporter.endpoint,
                resolved_endpoint,
            )
        exporter = _mutable_exporter
    exporter.configure(call_short_id=cid, evaluator_result_id=run_id, workspace_id=workspace)
    return exporter


def setup_tracer_provider(
    service_name: str = "efficientai-agent",
    *,
    exporter: Any = None,
    console_export: bool = False,
) -> bool:
    """Install a global ``TracerProvider`` with optional exporter. Returns ``False`` on failure."""
    if not OTEL_AVAILABLE:
        return False
    try:
        resource = Resource.create(
            {
                "service.name": service_name,
                "service.instance.id": os.getenv("HOSTNAME", "unknown"),
                "deployment.environment": os.getenv("ENVIRONMENT", "development"),
            }
        )
        provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(provider)
        if console_export:
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        if exporter is not None:
            provider.add_span_processor(BatchSpanProcessor(exporter))
        return True
    except Exception:
        logger.exception("Failed to set up OpenTelemetry tracing")
        return False


def _attach_correlation_processor(provider: Any, attrs: Optional[dict[str, str]]) -> None:
    """Add the correlation processor once. ``attrs`` (if given) become the default."""
    global _correlation_processor
    with _state_lock:
        if _correlation_processor is None:
            _correlation_processor = _CorrelationSpanProcessor(attrs or {})
            provider.add_span_processor(_correlation_processor)
        elif attrs is not None:
            _correlation_processor.update_attributes(attrs)


def ensure_export_pipeline(
    *,
    endpoint: str,
    api_key: str,
    workspace_id: Optional[str] = None,
    service_name: str = "efficientai-agent",
    console_export: bool = False,
) -> bool:
    """Make sure spans from this process are exported to EfficientAI. Idempotent.

    Uses the app's ``TracerProvider`` if it has one, otherwise installs one. The exporter
    carries only the API key and workspace; each span carries its own call id (see
    :mod:`efficientai_sdk.tracing.context`), so one pipeline serves concurrent calls.
    Returns ``False`` when OpenTelemetry is not installed or setup failed.
    """
    if not OTEL_AVAILABLE:
        return False
    key = (endpoint.rstrip("/"), api_key, workspace_id or None)
    with _state_lock:
        if key in _pipelines:
            return True
    try:
        exporter = OTLPSpanExporter(
            endpoint=key[0],
            headers=otlp_export_headers(api_key=api_key, workspace_id=workspace_id),
        )
        provider = trace.get_tracer_provider()
        if not isinstance(provider, TracerProvider):
            if not setup_tracer_provider(
                service_name, exporter=exporter, console_export=console_export
            ):
                return False
            provider = trace.get_tracer_provider()
        else:
            provider.add_span_processor(BatchSpanProcessor(exporter))
        _attach_correlation_processor(provider, None)
    except Exception:
        logger.exception("Failed to set up EfficientAI span export")
        return False
    with _state_lock:
        _pipelines[key] = exporter
    return True


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
    """Configure OpenTelemetry export to EfficientAI for the current call.

    Call once per call, after reading the call's SIP, webhook or handshake metadata.
    Works whether or not the process already has a ``TracerProvider``. Returns ``False``
    when OpenTelemetry is not installed.
    """
    global _exporter_attached
    if not OTEL_AVAILABLE:
        return False

    cid = _resolve_call_short_id(
        call_short_id=call_short_id, sip_headers=sip_headers, webhook_params=webhook_params
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
    exporter = create_otlp_exporter(
        endpoint=otlp_endpoint,
        api_key=api_key,
        call_short_id=cid,
        evaluator_result_id=run_id,
        workspace_id=workspace,
        mutable=True,
    )

    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        if not setup_tracer_provider(
            service_name, exporter=exporter, console_export=console_export
        ):
            return False
        _exporter_attached = True
        provider = trace.get_tracer_provider()
    elif not _exporter_attached:
        # The app installed its own provider: add our exporter to it once.
        provider.add_span_processor(BatchSpanProcessor(exporter))
        _exporter_attached = True

    if isinstance(provider, TracerProvider):
        _attach_correlation_processor(provider, attrs)
    # Tag spans from this task/thread with this call even when other calls run
    # concurrently in the same process (the processor default is only a fallback).
    set_call_attributes(attrs)
    return True


def flush_efficientai_tracing(timeout_millis: int = 30000) -> bool:
    """Block until queued spans are exported. Call before closing a trace session."""
    if not OTEL_AVAILABLE:
        return False
    try:
        provider = trace.get_tracer_provider()
        if isinstance(provider, TracerProvider):
            return bool(provider.force_flush(timeout_millis))
    except Exception:
        logger.exception("Failed to flush EfficientAI spans")
    return False


def _reset_for_tests() -> None:
    """Forget process-wide exporter state (tests only)."""
    global _correlation_processor, _mutable_exporter, _exporter_attached
    with _state_lock:
        # Processors can't be removed from a TracerProvider; switch the old one off.
        if _correlation_processor is not None:
            _correlation_processor.active = False
        _correlation_processor = None
        _mutable_exporter = None
        _exporter_attached = False
        _pipelines.clear()
