"""ClickHouse trace observation round-trip helpers."""

import json
from uuid import UUID

import pytest

from app.services.synthetic_traces.clickhouse_store import (
    OTEL_TRACE_ID_ATTR,
    _resolve_otel_trace_id,
    get_observations,
    insert_observations,
)


def test_resolve_otel_trace_id_prefers_span_value():
    attrs = {OTEL_TRACE_ID_ATTR: "stored"}
    assert _resolve_otel_trace_id("abc123", attrs, "fallback") == "abc123"


def test_resolve_otel_trace_id_uses_stored_attribute():
    attrs = {OTEL_TRACE_ID_ATTR: "stored"}
    assert _resolve_otel_trace_id(None, attrs, "fallback") == "stored"


def test_resolve_otel_trace_id_falls_back_to_trace_uuid_hex():
    assert _resolve_otel_trace_id(None, {}, "fallback") == "fallback"


def test_get_observations_restores_trace_id(monkeypatch):
    trace_uuid = UUID("e181db60-72ae-4f89-9374-4763935b98ee")
    attrs = {"gen_ai.operation.name": "stt"}

    class FakeResult:
        result_rows = [
            ("span1", None, "stt", None, 1, 2, attrs, [], None, None),
        ]

    class FakeClient:
        def query(self, *_args, **_kwargs):
            return FakeResult()

    monkeypatch.setattr(
        "app.services.synthetic_traces.clickhouse_store.get_client",
        lambda: FakeClient(),
    )

    spans = get_observations(trace_uuid)
    assert len(spans) == 1
    assert spans[0]["trace_id"] == trace_uuid.hex


def test_insert_observations_persists_otel_trace_id_in_attributes(monkeypatch):
    captured = {}

    class FakeClient:
        def insert(self, table, rows, column_names):
            captured["rows"] = rows
            captured["table"] = table

    monkeypatch.setattr(
        "app.services.synthetic_traces.clickhouse_store.get_client",
        lambda: FakeClient(),
    )

    workspace_id = UUID("11111111-1111-1111-1111-111111111111")
    trace_uuid = UUID("22222222-2222-2222-2222-222222222222")
    insert_observations(
        workspace_id=workspace_id,
        trace_uuid=trace_uuid,
        spans=[
            {
                "trace_id": "abcd1234",
                "span_id": "span1",
                "name": "stt",
                "attributes": {"gen_ai.operation.name": "stt"},
            }
        ],
    )

    attrs = json.loads(captured["rows"][0][8])
    assert attrs[OTEL_TRACE_ID_ATTR] == "abcd1234"
