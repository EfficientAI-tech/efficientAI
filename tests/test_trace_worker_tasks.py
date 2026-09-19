"""Tests for Phase 2 trace batch storage and worker derive."""

from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

from app.models.database import SyntheticTraceSpanBatch
from app.services.synthetic_traces.ingest_pipeline import ingest_otlp_batch_async, persist_span_batch
from app.services.synthetic_traces.span_storage import dedupe_spans, load_batches_spans
from app.services.synthetic_traces.trace_service import derive_trace_turns, open_trace_session


def _stt_span(call_short_id: str, span_id: str, turn: int = 1) -> dict:
    return {
        "trace_id": "abc",
        "span_id": span_id,
        "name": "stt",
        "attributes": {
            "efficientai.call_short_id": call_short_id,
            "turn.number": turn,
            "gen_ai.operation.name": "stt",
            "metrics.ttfb": 0.12,
        },
    }


def test_dedupe_spans_keeps_first_occurrence():
    spans = [
        {"trace_id": "t1", "span_id": "a"},
        {"trace_id": "t1", "span_id": "a"},
        {"trace_id": "t1", "span_id": "b"},
    ]
    assert len(dedupe_spans(spans)) == 2


def test_persist_span_batch_appends_rows(db_session, org_id, default_workspace):
    trace = open_trace_session(
        db_session,
        organization_id=org_id,
        workspace_id=default_workspace.id,
        transport="webrtc",
    )
    call_short_id = trace.call_short_id
    assert call_short_id

    persist_span_batch(db_session, trace, [_stt_span(call_short_id, "s1")])
    persist_span_batch(db_session, trace, [_stt_span(call_short_id, "s2")])

    batches = (
        db_session.query(SyntheticTraceSpanBatch)
        .filter(SyntheticTraceSpanBatch.synthetic_call_trace_id == trace.id)
        .order_by(SyntheticTraceSpanBatch.seq.asc())
        .all()
    )
    assert len(batches) == 2
    loaded = load_batches_spans(db_session, trace.id)
    assert len(loaded) == 2


@patch("app.services.synthetic_traces.ingest_pipeline.schedule_derive")
def test_ingest_otlp_batch_async_persists_without_sync_derive(
    mock_schedule,
    db_session,
    org_id,
    default_workspace,
):
    trace = open_trace_session(
        db_session,
        organization_id=org_id,
        workspace_id=default_workspace.id,
        transport="webrtc",
    )
    call_short_id = trace.call_short_id
    spans = [_stt_span(call_short_id, "s1")]

    result_trace, accepted, correlated = ingest_otlp_batch_async(
        db_session,
        organization_id=org_id,
        spans=spans,
        header_call_short_id=call_short_id,
        workspace_id=default_workspace.id,
    )
    assert accepted == 1
    assert correlated is True
    assert result_trace is not None
    assert result_trace.derive_pending is True
    mock_schedule.assert_called_once()


def test_derive_trace_turns_updates_header_metrics(db_session, org_id, default_workspace):
    trace = open_trace_session(
        db_session,
        organization_id=org_id,
        workspace_id=default_workspace.id,
        transport="webrtc",
    )
    call_short_id = trace.call_short_id
    persist_span_batch(
        db_session,
        trace,
        [_stt_span(call_short_id, "s1"), _stt_span(call_short_id, "s2", turn=2)],
    )
    db_session.refresh(trace)

    updated = derive_trace_turns(db_session, trace_id=trace.id)
    assert updated is not None
    assert updated.derive_pending is False
    assert updated.turn_count >= 1
