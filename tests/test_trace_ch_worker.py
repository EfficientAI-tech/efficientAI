"""Tests for ClickHouse trace worker path (process_s3_otlp_batch, ingest_otlp_batch_ch)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.services.synthetic_traces.ch_trace_ops import load_trace_detail_ch
from app.services.synthetic_traces.clickhouse_store import TraceRecord
from app.services.synthetic_traces.ingest_pipeline import (
    ingest_otlp_batch_ch,
    process_s3_otlp_batch,
)


def _stt_span(call_short_id: str, span_id: str = "s1") -> dict:
    return {
        "trace_id": "abc",
        "span_id": span_id,
        "name": "stt",
        "attributes": {
            "efficientai.call_short_id": call_short_id,
            "gen_ai.operation.name": "stt",
        },
    }


@patch("app.services.synthetic_traces.ingest_pipeline.schedule_derive")
@patch("app.services.synthetic_traces.ch_trace_ops.persist_spans_ch")
@patch("app.services.synthetic_traces.ingest_pipeline.correlate_batch_ch")
@patch("app.services.synthetic_traces.ingest_pipeline.resolve_trace_uuid_for_s3_ingest")
@patch("app.services.synthetic_traces.ch_trace_ops.use_ch", return_value=True)
def test_ingest_otlp_batch_ch_persists_and_schedules_derive(
    _use_ch,
    mock_resolve,
    mock_correlate,
    mock_persist,
    mock_derive,
    db_session,
    org_id,
    default_workspace,
):
    trace_id = uuid4()
    mock_resolve.return_value = trace_id
    trace = MagicMock()
    trace.id = trace_id
    mock_correlate.return_value = (trace, True)

    _trace, accepted, correlated = ingest_otlp_batch_ch(
        db_session,
        organization_id=org_id,
        spans=[_stt_span("482931")],
        header_call_short_id="482931",
        workspace_id=default_workspace.id,
    )

    assert accepted == 1
    assert correlated is True
    mock_persist.assert_called_once()
    mock_derive.assert_called_once_with(trace_id)


@patch("app.services.synthetic_traces.ingest_pipeline.schedule_derive")
@patch("app.services.synthetic_traces.ch_trace_ops.persist_spans_ch")
@patch("app.services.synthetic_traces.ingest_pipeline.correlate_batch_ch")
@patch("app.services.storage.blob_storage_service.blob_storage_service.download_file_by_key")
@patch("app.services.synthetic_traces.ingest_pipeline.parse_otlp_body")
def test_process_s3_otlp_batch_downloads_parses_and_persists(
    mock_parse,
    mock_download,
    mock_correlate,
    mock_persist,
    mock_derive,
    db_session,
    org_id,
    default_workspace,
):
    trace_id = uuid4()
    mock_download.return_value = b'{"resourceSpans":[]}'
    mock_parse.return_value = ([_stt_span("482931")], "json")
    trace = MagicMock()
    trace.id = trace_id
    mock_correlate.return_value = (trace, True)

    process_s3_otlp_batch(
        s3_key="audio/org/ws/traces/x/batches/1.json",
        organization_id=org_id,
        workspace_id=default_workspace.id,
        trace_uuid=trace_id,
        seq=1,
        content_type="application/json",
        header_call_short_id="482931",
        db=db_session,
    )

    mock_download.assert_called_once()
    mock_persist.assert_called_once()
    mock_derive.assert_called_once_with(trace_id)


@patch("app.services.synthetic_traces.ch_trace_ops.close_and_offload_trace_ch")
@patch("app.services.synthetic_traces.clickhouse_store.get_trace_by_call_short_id")
def test_close_trace_session_ch_finds_clickhouse_trace(mock_get_trace, mock_close):
    from app.services.synthetic_traces.ch_trace_ops import close_trace_session_ch

    trace_id = uuid4()
    org_id = uuid4()
    trace = MagicMock()
    trace.id = trace_id
    trace.status = "open"
    mock_get_trace.return_value = trace
    mock_close.return_value = trace

    closed = close_trace_session_ch(
        MagicMock(),
        organization_id=org_id,
        call_short_id="632776",
        workspace_id=uuid4(),
    )

    assert closed is trace
    mock_get_trace.assert_called_once()
    mock_close.assert_called_once()


@patch("app.services.synthetic_traces.ch_trace_ops.get_live_turns", return_value=None)
@patch("app.services.synthetic_traces.ch_trace_ops.get_observations")
def test_load_trace_detail_ch_pipeline_models_without_spans_in_response(
    mock_get_observations,
    _mock_live_turns,
):
    trace_id = uuid4()
    trace = TraceRecord(
        id=trace_id,
        organization_id=uuid4(),
        workspace_id=uuid4(),
        call_short_id="632776",
        environment="pre_prod",
        transport="webrtc",
        tier="black_box",
        status="closed",
        started_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        turns=[{"turn_number": 1, "llm_ttfb_ms": 100.0}],
    )
    mock_get_observations.return_value = [
        {
            "trace_id": "abc",
            "span_id": "s1",
            "name": "llm",
            "attributes": {
                "gen_ai.operation.name": "chat",
                "gen_ai.request.model": "accounts/fireworks/models/deepseek-v4",
                "gen_ai.provider.name": "fireworks",
            },
        }
    ]

    detail = load_trace_detail_ch(trace, include_spans=False)

    assert detail["otel_spans"] == []
    assert detail["pipeline_models"]["llm"]["provider"] == "fireworks"
    assert detail["pipeline_models"]["llm"]["model"] == "deepseek-v4"
