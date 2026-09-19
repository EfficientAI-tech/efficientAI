"""Tests for in-process playground OTLP export."""

from app.services.synthetic_traces.internal_otlp_exporter import readable_span_to_dict
from app.services.synthetic_traces.trace_service import (
    get_trace_by_call_short_id,
    ingest_otlp_spans,
    open_trace_session,
)


class _FakeSpanContext:
    def __init__(self, trace_id: int, span_id: int):
        self.trace_id = trace_id
        self.span_id = span_id


class _FakeSpan:
    def __init__(self):
        self.name = "stt"
        self.attributes = {
            "efficientai.call_short_id": "482931",
            "turn.number": 1,
            "gen_ai.operation.name": "stt",
            "metrics.ttfb": 0.12,
            "transcript": "hello",
        }
        self.events = []
        self.parent = None
        self.start_time = 1_000_000_000
        self.end_time = 2_000_000_000
        self._context = _FakeSpanContext(0xABC, 0x1)

    def get_span_context(self):
        return self._context


def test_readable_span_to_dict_normalizes_attributes():
    payload = readable_span_to_dict(_FakeSpan())
    assert payload["name"] == "stt"
    assert payload["attributes"]["efficientai.call_short_id"] == "482931"
    assert payload["trace_id"] == format(0xABC, "032x")


def test_internal_exporter_ingests_via_readable_span_dict(
    db_session,
    org_id,
    default_workspace,
):
    call_short_id = "482931"
    open_trace_session(
        db_session,
        organization_id=org_id,
        workspace_id=default_workspace.id,
        call_short_id=call_short_id,
        transport="websocket",
    )

    trace, accepted, correlated = ingest_otlp_spans(
        db_session,
        organization_id=org_id,
        spans=[readable_span_to_dict(_FakeSpan())],
        header_call_short_id=call_short_id,
        workspace_id=default_workspace.id,
    )

    assert accepted == 1
    assert correlated is True
    assert trace is not None
    stored = get_trace_by_call_short_id(
        db_session,
        organization_id=org_id,
        call_short_id=call_short_id,
        workspace_id=default_workspace.id,
    )
    assert stored is not None
    assert stored.turn_count >= 1
