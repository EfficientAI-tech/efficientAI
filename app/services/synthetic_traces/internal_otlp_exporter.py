"""In-process OTLP span exporter for playground voice pipelines."""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any, Dict, Optional, Sequence, Tuple
from uuid import UUID

from loguru import logger

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


def readable_span_to_dict(span: ReadableSpan) -> Dict[str, Any]:
    attributes = {
        str(key): _attr_value(val) for key, val in (span.attributes or {}).items()
    }
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
) -> Optional[Tuple[str, str, Optional[str]]]:
    from efficientai.integrations.efficientai_traces.correlation import (
        ATTR_AGENT_ID,
        ATTR_CALL_SHORT_ID,
        ATTR_WORKSPACE_ID,
    )

    call_short_id = attributes.get(ATTR_CALL_SHORT_ID)
    workspace_id = attributes.get(ATTR_WORKSPACE_ID)
    if not call_short_id or not workspace_id:
        return None
    agent_id = attributes.get(ATTR_AGENT_ID)
    return str(call_short_id), str(workspace_id), str(agent_id) if agent_id else None


class InternalOtlpSpanExporter(SpanExporter):  # type: ignore[misc]
    """Export Pipecat spans directly into synthetic trace storage (no HTTP hop)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._organization_id: Optional[UUID] = None

    def configure(self, *, organization_id: UUID) -> None:
        with self._lock:
            self._organization_id = organization_id

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        if not spans or not _OTEL_AVAILABLE:
            return SpanExportResult.SUCCESS

        with self._lock:
            organization_id = self._organization_id

        if organization_id is None:
            logger.warning("Internal OTLP export skipped: exporter not configured")
            return SpanExportResult.FAILURE

        grouped: dict[tuple[str, str], list[ReadableSpan]] = defaultdict(list)
        skipped = 0
        for span in spans:
            attrs = {str(k): _attr_value(v) for k, v in (span.attributes or {}).items()}
            correlation = _span_correlation_from_attributes(attrs)
            if not correlation:
                skipped += 1
                continue
            call_short_id, workspace_id, _ = correlation
            grouped[(call_short_id, workspace_id)].append(span)

        if skipped:
            logger.debug("Internal OTLP export skipped {} spans without correlation attrs", skipped)
        if not grouped:
            return SpanExportResult.SUCCESS

        from app.database import SessionLocal
        from app.services.synthetic_traces.trace_service import ingest_otlp_spans

        db = SessionLocal()
        try:
            for (call_short_id, workspace_id), batch in grouped.items():
                payload = [readable_span_to_dict(span) for span in batch]
                first_attrs = payload[0].get("attributes") if payload else {}
                correlation = (
                    _span_correlation_from_attributes(first_attrs or {})
                    if isinstance(first_attrs, dict)
                    else None
                )
                agent_id = correlation[2] if correlation else None
                ingest_otlp_spans(
                    db,
                    organization_id=organization_id,
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
