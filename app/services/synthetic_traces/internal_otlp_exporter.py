"""In-process OTLP span exporter for playground voice pipelines."""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional, Sequence
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


class InternalOtlpSpanExporter(SpanExporter):  # type: ignore[misc]
    """Export Pipecat spans directly into synthetic trace storage (no HTTP hop)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._organization_id: Optional[UUID] = None
        self._workspace_id: Optional[UUID] = None
        self._call_short_id: Optional[str] = None
        self._agent_id: Optional[str] = None

    def configure(
        self,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        call_short_id: str,
        agent_id: Optional[str] = None,
    ) -> None:
        with self._lock:
            self._organization_id = organization_id
            self._workspace_id = workspace_id
            self._call_short_id = call_short_id
            self._agent_id = agent_id

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        if not spans or not _OTEL_AVAILABLE:
            return SpanExportResult.SUCCESS

        with self._lock:
            organization_id = self._organization_id
            workspace_id = self._workspace_id
            call_short_id = self._call_short_id
            agent_id = self._agent_id

        if organization_id is None or workspace_id is None or not call_short_id:
            logger.warning("Internal OTLP export skipped: exporter not configured")
            return SpanExportResult.FAILURE

        from app.database import SessionLocal
        from app.services.synthetic_traces.trace_service import ingest_otlp_spans

        payload = [readable_span_to_dict(span) for span in spans]
        db = SessionLocal()
        try:
            ingest_otlp_spans(
                db,
                organization_id=organization_id,
                spans=payload,
                header_call_short_id=call_short_id,
                header_agent_id=agent_id,
                workspace_id=workspace_id,
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
