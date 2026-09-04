"""Tests for in-process OTLP exporter call isolation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.services.synthetic_traces.internal_otlp_exporter import InternalOtlpSpanExporter


def _readable_span(*, call_short_id: str, workspace_id: str, name: str = "span"):
    from efficientai.integrations.efficientai_traces.correlation import (
        ATTR_CALL_SHORT_ID,
        ATTR_WORKSPACE_ID,
    )

    return SimpleNamespace(
        attributes={
            ATTR_CALL_SHORT_ID: call_short_id,
            ATTR_WORKSPACE_ID: str(workspace_id),
        },
        events=[],
        name=name,
        parent=None,
        start_time=1,
        end_time=2,
        get_span_context=lambda: SimpleNamespace(trace_id=1, span_id=2),
    )


def test_internal_exporter_groups_spans_by_correlation_attributes():
    org_id = uuid4()
    ws_a = uuid4()
    ws_b = uuid4()
    exporter = InternalOtlpSpanExporter()
    exporter.configure(organization_id=org_id)

    spans = [
        _readable_span(call_short_id="111111", workspace_id=ws_a, name="a1"),
        _readable_span(call_short_id="222222", workspace_id=ws_b, name="b1"),
        _readable_span(call_short_id="111111", workspace_id=ws_a, name="a2"),
    ]

    with patch(
        "app.services.synthetic_traces.trace_service.ingest_otlp_spans"
    ) as ingest_mock, patch(
        "app.database.SessionLocal"
    ) as session_local:
        session_local.return_value = MagicMock()
        ingest_mock.return_value = (None, 1, True)

        from opentelemetry.sdk.trace.export import SpanExportResult

        result = exporter.export(spans)

    assert result == SpanExportResult.SUCCESS
    assert ingest_mock.call_count == 2

    batches = {
        (
            call.kwargs["header_call_short_id"],
            str(call.kwargs["workspace_id"]),
        )
        for call in ingest_mock.call_args_list
    }
    assert ("111111", str(ws_a)) in batches
    assert ("222222", str(ws_b)) in batches

    for call in ingest_mock.call_args_list:
        assert call.kwargs["organization_id"] == org_id


def test_internal_exporter_skips_spans_without_correlation_attributes():
    org_id = uuid4()
    exporter = InternalOtlpSpanExporter()
    exporter.configure(organization_id=org_id)

    span = SimpleNamespace(
        attributes={},
        events=[],
        name="orphan",
        parent=None,
        start_time=1,
        end_time=2,
        get_span_context=lambda: SimpleNamespace(trace_id=1, span_id=2),
    )

    with patch(
        "app.services.synthetic_traces.trace_service.ingest_otlp_spans"
    ) as ingest_mock, patch(
        "app.database.SessionLocal"
    ) as session_local:
        session_local.return_value = MagicMock()

        from opentelemetry.sdk.trace.export import SpanExportResult

        result = exporter.export([span])

    assert result == SpanExportResult.SUCCESS
    ingest_mock.assert_not_called()
