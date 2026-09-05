"""Tests for in-process OTLP exporter call isolation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.services.synthetic_traces.internal_otlp_exporter import (
    InternalOtlpSpanExporter,
    clear_trace_correlation_cache,
)


def _readable_span(
    *,
    call_short_id: str,
    workspace_id: str,
    organization_id: str,
    name: str = "span",
):
    from efficientai.integrations.efficientai_traces.correlation import (
        ATTR_CALL_SHORT_ID,
        ATTR_ORGANIZATION_ID,
        ATTR_WORKSPACE_ID,
    )

    return SimpleNamespace(
        attributes={
            ATTR_CALL_SHORT_ID: call_short_id,
            ATTR_WORKSPACE_ID: str(workspace_id),
            ATTR_ORGANIZATION_ID: str(organization_id),
        },
        events=[],
        name=name,
        parent=None,
        start_time=1,
        end_time=2,
        get_span_context=lambda: SimpleNamespace(trace_id=1, span_id=2),
    )


def test_internal_exporter_groups_spans_by_correlation_attributes():
    clear_trace_correlation_cache()
    org_id = uuid4()
    ws_a = uuid4()
    ws_b = uuid4()
    exporter = InternalOtlpSpanExporter()

    spans = [
        _readable_span(call_short_id="111111", workspace_id=ws_a, organization_id=org_id, name="a1"),
        _readable_span(call_short_id="222222", workspace_id=ws_b, organization_id=org_id, name="b1"),
        _readable_span(call_short_id="111111", workspace_id=ws_a, organization_id=org_id, name="a2"),
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


def test_internal_exporter_uses_organization_id_from_span_not_shared_config():
    """Concurrent calls must not misattribute spans via a shared exporter config."""
    clear_trace_correlation_cache()
    org_a = uuid4()
    org_b = uuid4()
    ws = uuid4()
    exporter = InternalOtlpSpanExporter()

    spans = [
        _readable_span(call_short_id="111111", workspace_id=ws, organization_id=org_a, name="tenant-a"),
        _readable_span(call_short_id="222222", workspace_id=ws, organization_id=org_b, name="tenant-b"),
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

    org_by_call = {
        call.kwargs["header_call_short_id"]: call.kwargs["organization_id"]
        for call in ingest_mock.call_args_list
    }
    assert org_by_call["111111"] == org_a
    assert org_by_call["222222"] == org_b


def test_internal_exporter_inherits_correlation_from_conversation_span_in_same_trace():
    clear_trace_correlation_cache()
    from efficientai.integrations.efficientai_traces.correlation import (
        ATTR_CALL_SHORT_ID,
        ATTR_ORGANIZATION_ID,
        ATTR_WORKSPACE_ID,
    )

    org_id = uuid4()
    ws_id = uuid4()
    trace_id = 42
    exporter = InternalOtlpSpanExporter()

    conversation = SimpleNamespace(
        attributes={
            ATTR_CALL_SHORT_ID: "530430",
            ATTR_WORKSPACE_ID: str(ws_id),
            ATTR_ORGANIZATION_ID: str(org_id),
        },
        events=[],
        name="conversation",
        parent=None,
        start_time=1,
        end_time=2,
        get_span_context=lambda: SimpleNamespace(trace_id=trace_id, span_id=1),
    )
    turn = SimpleNamespace(
        attributes={"turn.number": 1},
        events=[],
        name="turn",
        parent=None,
        start_time=3,
        end_time=4,
        get_span_context=lambda: SimpleNamespace(trace_id=trace_id, span_id=2),
    )
    stt = SimpleNamespace(
        attributes={"gen_ai.system": "sarvam"},
        events=[],
        name="stt",
        parent=None,
        start_time=5,
        end_time=6,
        get_span_context=lambda: SimpleNamespace(trace_id=trace_id, span_id=3),
    )

    with patch(
        "app.services.synthetic_traces.trace_service.ingest_otlp_spans"
    ) as ingest_mock, patch(
        "app.database.SessionLocal"
    ) as session_local:
        session_local.return_value = MagicMock()
        ingest_mock.return_value = (None, 3, True)

        from opentelemetry.sdk.trace.export import SpanExportResult

        result = exporter.export([conversation, turn, stt])

    assert result == SpanExportResult.SUCCESS
    ingest_mock.assert_called_once()
    payload = ingest_mock.call_args.kwargs["spans"]
    assert len(payload) == 3
    for span_dict in payload:
        attrs = span_dict["attributes"]
        assert attrs[ATTR_CALL_SHORT_ID] == "530430"
        assert attrs[ATTR_WORKSPACE_ID] == str(ws_id)
        assert attrs[ATTR_ORGANIZATION_ID] == str(org_id)


def test_internal_exporter_skips_spans_without_correlation_attributes():
    clear_trace_correlation_cache()
    org_id = uuid4()
    exporter = InternalOtlpSpanExporter()

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


def test_internal_exporter_inherits_correlation_across_export_batches():
    from efficientai.integrations.efficientai_traces.correlation import (
        ATTR_CALL_SHORT_ID,
        ATTR_ORGANIZATION_ID,
        ATTR_WORKSPACE_ID,
    )

    clear_trace_correlation_cache()
    org_id = uuid4()
    ws_id = uuid4()
    trace_id = 99
    exporter = InternalOtlpSpanExporter()

    conversation = SimpleNamespace(
        attributes={
            ATTR_CALL_SHORT_ID: "664417",
            ATTR_WORKSPACE_ID: str(ws_id),
            ATTR_ORGANIZATION_ID: str(org_id),
        },
        events=[],
        name="conversation",
        parent=None,
        start_time=1,
        end_time=2,
        get_span_context=lambda: SimpleNamespace(trace_id=trace_id, span_id=1),
    )
    stt = SimpleNamespace(
        attributes={"gen_ai.system": "sarvam"},
        events=[],
        name="stt",
        parent=None,
        start_time=5,
        end_time=6,
        get_span_context=lambda: SimpleNamespace(trace_id=trace_id, span_id=3),
    )

    with patch(
        "app.services.synthetic_traces.trace_service.ingest_otlp_spans"
    ) as ingest_mock, patch(
        "app.database.SessionLocal"
    ) as session_local:
        session_local.return_value = MagicMock()
        ingest_mock.return_value = (None, 1, True)

        from opentelemetry.sdk.trace.export import SpanExportResult

        assert exporter.export([conversation]) == SpanExportResult.SUCCESS
        assert exporter.export([stt]) == SpanExportResult.SUCCESS

    assert ingest_mock.call_count == 2
    stt_payload = ingest_mock.call_args_list[1].kwargs["spans"]
    assert len(stt_payload) == 1
    attrs = stt_payload[0]["attributes"]
    assert attrs[ATTR_CALL_SHORT_ID] == "664417"
    assert attrs[ATTR_WORKSPACE_ID] == str(ws_id)
    assert attrs[ATTR_ORGANIZATION_ID] == str(org_id)


def test_internal_exporter_inherits_correlation_from_parent_turn_span():
    from efficientai.integrations.efficientai_traces.correlation import (
        ATTR_CALL_SHORT_ID,
        ATTR_ORGANIZATION_ID,
        ATTR_WORKSPACE_ID,
    )

    clear_trace_correlation_cache()
    org_id = uuid4()
    ws_id = uuid4()
    trace_id = 77
    exporter = InternalOtlpSpanExporter()

    turn_parent = SimpleNamespace(span_id=2)
    turn = SimpleNamespace(
        attributes={
            ATTR_CALL_SHORT_ID: "530430",
            ATTR_WORKSPACE_ID: str(ws_id),
            ATTR_ORGANIZATION_ID: str(org_id),
            "turn.number": 2,
        },
        events=[],
        name="turn",
        parent=None,
        start_time=3,
        end_time=4,
        get_span_context=lambda: SimpleNamespace(trace_id=trace_id, span_id=2),
    )
    llm = SimpleNamespace(
        attributes={"gen_ai.operation.name": "chat"},
        events=[],
        name="llm",
        parent=turn_parent,
        start_time=5,
        end_time=6,
        get_span_context=lambda: SimpleNamespace(trace_id=trace_id, span_id=4),
    )

    with patch(
        "app.services.synthetic_traces.trace_service.ingest_otlp_spans"
    ) as ingest_mock, patch(
        "app.database.SessionLocal"
    ) as session_local:
        session_local.return_value = MagicMock()
        ingest_mock.return_value = (None, 2, True)

        from opentelemetry.sdk.trace.export import SpanExportResult

        result = exporter.export([turn, llm])

    assert result == SpanExportResult.SUCCESS
    ingest_mock.assert_called_once()
    payload = ingest_mock.call_args.kwargs["spans"]
    llm_attrs = next(row["attributes"] for row in payload if row["name"] == "llm")
    assert llm_attrs[ATTR_CALL_SHORT_ID] == "530430"
