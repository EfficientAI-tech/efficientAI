"""In-process OTLP span exporter for playground voice pipelines."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Optional, Sequence, Tuple
from uuid import UUID

from loguru import logger

_MAX_TRACE_CORRELATION_CACHE = 256
_TRACE_CORRELATION_CACHE: Dict[int, Tuple[str, str, str, Optional[str]]] = {}


def clear_trace_correlation_cache() -> None:
    """Test-only reset. Do not call on per-call flush — cache is process-wide."""
    _TRACE_CORRELATION_CACHE.clear()

try:
    from opentelemetry.sdk.trace import ReadableSpan
    from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False
    SpanExporter = object  # type: ignore[misc,assignment]
    ReadableSpan = object  # type: ignore[misc,assignment]
    SpanExportResult = object  # type: ignore[misc,assignment]


def _attr_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_attr_value(v) for v in value]
    return str(value)


def _span_attributes(span: ReadableSpan) -> Dict[str, Any]:
    return {str(key): _attr_value(val) for key, val in (span.attributes or {}).items()}


def _apply_correlation_to_attributes(
    attributes: Dict[str, Any],
    correlation: Tuple[str, str, str, Optional[str]],
) -> Dict[str, Any]:
    from efficientai.integrations.efficientai_traces.correlation import (
        ATTR_AGENT_ID,
        ATTR_CALL_SHORT_ID,
        ATTR_ORGANIZATION_ID,
        ATTR_WORKSPACE_ID,
    )

    call_short_id, workspace_id, organization_id, agent_id = correlation
    enriched = dict(attributes)
    enriched[ATTR_CALL_SHORT_ID] = call_short_id
    enriched[ATTR_WORKSPACE_ID] = workspace_id
    enriched[ATTR_ORGANIZATION_ID] = organization_id
    if agent_id:
        enriched[ATTR_AGENT_ID] = agent_id
    return enriched


def _parent_span_id(span: ReadableSpan) -> Optional[str]:
    if span.parent is not None:
        return format(span.parent.span_id, "016x")
    return None


def _resolve_span_attributes(
    spans: Sequence[ReadableSpan],
) -> list[tuple[ReadableSpan, Dict[str, Any]]]:
    """Inherit EfficientAI correlation attrs across spans, batches, and parent chains."""
    trace_correlation: Dict[int, Tuple[str, str, str, Optional[str]]] = dict(
        _TRACE_CORRELATION_CACHE
    )
    attrs_by_span_id: Dict[str, Dict[str, Any]] = {}
    spans_by_id: Dict[str, ReadableSpan] = {}
    span_entries: list[tuple[ReadableSpan, str, Dict[str, Any]]] = []

    for span in spans:
        span_id = format(span.get_span_context().span_id, "016x")
        attrs = _span_attributes(span)
        span_entries.append((span, span_id, attrs))
        attrs_by_span_id[span_id] = attrs
        spans_by_id[span_id] = span
        correlation = _span_correlation_from_attributes(attrs)
        if correlation:
            trace_correlation[span.get_span_context().trace_id] = correlation

    resolved: list[tuple[ReadableSpan, Dict[str, Any]]] = []
    for span, span_id, raw_attrs in span_entries:
        attrs = dict(raw_attrs)

        if not _span_correlation_from_attributes(attrs):
            parent_id = _parent_span_id(span)
            visited: set[str] = set()
            while parent_id and parent_id not in visited:
                visited.add(parent_id)
                parent_attrs = attrs_by_span_id.get(parent_id)
                if parent_attrs:
                    inherited = _span_correlation_from_attributes(parent_attrs)
                    if inherited:
                        attrs = _apply_correlation_to_attributes(attrs, inherited)
                        break
                    parent_span = spans_by_id.get(parent_id)
                    parent_id = _parent_span_id(parent_span) if parent_span else None
                else:
                    break

        if not _span_correlation_from_attributes(attrs):
            cached = trace_correlation.get(span.get_span_context().trace_id)
            if cached:
                attrs = _apply_correlation_to_attributes(attrs, cached)

        correlation = _span_correlation_from_attributes(attrs)
        if correlation:
            trace_correlation[span.get_span_context().trace_id] = correlation
        resolved.append((span, attrs))

    for trace_id, correlation in trace_correlation.items():
        _TRACE_CORRELATION_CACHE[trace_id] = correlation
    while len(_TRACE_CORRELATION_CACHE) > _MAX_TRACE_CORRELATION_CACHE:
        _TRACE_CORRELATION_CACHE.pop(next(iter(_TRACE_CORRELATION_CACHE)))

    return resolved


def readable_span_to_dict(
    span: ReadableSpan,
    attributes: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    attributes = attributes or _span_attributes(span)
    events = []
    for event in span.events or []:
        events.append(
            {
                "name": event.name,
                "time_unix_nano": event.timestamp,
                "attributes": {
                    str(key): _attr_value(val)
                    for key, val in (event.attributes or {}).items()
                },
            }
        )
    ctx = span.get_span_context()
    parent_span_id = None
    if span.parent is not None:
        parent_span_id = format(span.parent.span_id, "016x")
    return {
        "trace_id": format(ctx.trace_id, "032x"),
        "span_id": format(ctx.span_id, "016x"),
        "parent_span_id": parent_span_id,
        "name": span.name or "",
        "start_time_unix_nano": span.start_time,
        "end_time_unix_nano": span.end_time,
        "attributes": attributes,
        "events": events,
    }


def _span_correlation_from_attributes(
    attributes: Dict[str, Any],
) -> Optional[Tuple[str, str, str, Optional[str]]]:
    from efficientai.integrations.efficientai_traces.correlation import (
        ATTR_AGENT_ID,
        ATTR_CALL_SHORT_ID,
        ATTR_ORGANIZATION_ID,
        ATTR_WORKSPACE_ID,
    )

    call_short_id = attributes.get(ATTR_CALL_SHORT_ID)
    workspace_id = attributes.get(ATTR_WORKSPACE_ID)
    organization_id = attributes.get(ATTR_ORGANIZATION_ID)
    if not call_short_id or not workspace_id or not organization_id:
        return None
    agent_id = attributes.get(ATTR_AGENT_ID)
    return (
        str(call_short_id),
        str(workspace_id),
        str(organization_id),
        str(agent_id) if agent_id else None,
    )


class InternalOtlpSpanExporter(SpanExporter):  # type: ignore[misc]
    """Export Pipecat spans directly into synthetic trace storage (no HTTP hop)."""

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        if not spans or not _OTEL_AVAILABLE:
            return SpanExportResult.SUCCESS

        grouped: dict[tuple[str, str, str], list[tuple[ReadableSpan, Dict[str, Any]]]] = defaultdict(list)
        skipped = 0
        for span, attrs in _resolve_span_attributes(spans):
            correlation = _span_correlation_from_attributes(attrs)
            if not correlation:
                skipped += 1
                continue
            call_short_id, workspace_id, organization_id, _ = correlation
            grouped[(organization_id, call_short_id, workspace_id)].append((span, attrs))

        if skipped:
            logger.debug("Internal OTLP export skipped {} spans without correlation attrs", skipped)
        if not grouped:
            return SpanExportResult.SUCCESS

        from app.database import SessionLocal
        from app.services.synthetic_traces.trace_service import ingest_otlp_spans

        db = SessionLocal()
        try:
            for (organization_id, call_short_id, workspace_id), batch in grouped.items():
                payload = [readable_span_to_dict(span, attrs) for span, attrs in batch]
                first_attrs = payload[0].get("attributes") if payload else {}
                correlation = (
                    _span_correlation_from_attributes(first_attrs or {})
                    if isinstance(first_attrs, dict)
                    else None
                )
                agent_id = correlation[3] if correlation else None
                ingest_otlp_spans(
                    db,
                    organization_id=UUID(organization_id),
                    spans=payload,
                    header_call_short_id=call_short_id,
                    header_agent_id=agent_id,
                    workspace_id=UUID(workspace_id),
                )
        except Exception as exc:
            logger.warning("Internal OTLP ingest failed: {}", exc)
            return SpanExportResult.FAILURE
        finally:
            db.close()
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True
