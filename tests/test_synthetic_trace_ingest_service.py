"""Tests for synthetic trace OTLP ingest correlation."""

from uuid import uuid4

from app.models.database import (
    CallRecording,
    CallRecordingSource,
    EvaluatorResult,
    EvaluatorResultStatus,
    SyntheticCallTrace,
)
from app.models.enums import CallRecordingStatus
from app.services.synthetic_traces.otlp_mapper import (
    derive_turns_from_spans,
    extract_correlation_ids,
    filter_spans_for_trace,
    merge_tier1_and_otel_turns,
)
from app.services.synthetic_traces.trace_service import (
    backfill_missing_traces_from_call_recordings,
    close_trace_session,
    ingest_json_spans,
    ingest_otlp_spans,
    list_traces,
    open_trace,
    open_trace_session,
)


def _stt_span(call_short_id: str, turn: int = 1) -> dict:
    return {
        "trace_id": "abc",
        "span_id": f"stt-{turn}",
        "name": "stt",
        "attributes": {
            "efficientai.call_short_id": call_short_id,
            "turn.number": turn,
            "gen_ai.operation.name": "stt",
            "metrics.ttfb": 0.12,
            "transcript": "hello",
        },
    }


def test_extract_correlation_ids_rejects_invalid_call_short_id():
    ids = extract_correlation_ids(
        [{"attributes": {"efficientai.call_short_id": "not-a-id"}}]
    )
    assert ids.get("call_short_id") is None

def test_ingest_otlp_spans_correlates_by_call_short_id(
    db_session,
    org_id,
    default_workspace,
):
    call_short_id = "482931"
    result = EvaluatorResult(
        id=uuid4(),
        result_id="900001",
        organization_id=org_id,
        workspace_id=default_workspace.id,
        evaluator_id=uuid4(),
        agent_id=uuid4(),
        name="Phone test",
        status=EvaluatorResultStatus.QUEUED.value,
    )
    db_session.add(result)
    db_session.commit()

    open_trace(
        db_session,
        organization_id=org_id,
        workspace_id=default_workspace.id,
        evaluator_result_id=result.id,
        agent_id=result.agent_id,
        call_short_id=call_short_id,
        transport="phone",
    )

    trace, accepted, correlated = ingest_otlp_spans(
        db_session,
        organization_id=org_id,
        spans=[_stt_span(call_short_id)],
        header_call_short_id=call_short_id,
    )

    assert accepted == 1
    assert correlated is True
    assert trace is not None
    assert trace.call_short_id == call_short_id
    assert trace.turn_count == 1
    assert trace.tier == "component"

    detail_turns = trace.synthetic_trace_payload.turns if hasattr(trace, "synthetic_trace_payload") else None
    if detail_turns is None:
        from app.models.database import SyntheticTracePayload

        payload = (
            db_session.query(SyntheticTracePayload)
            .filter(SyntheticTracePayload.synthetic_call_trace_id == trace.id)
            .first()
        )
        detail_turns = payload.turns

    assert detail_turns[0]["stt_ttfb_ms"] == 120.0
    assert detail_turns[0]["transcript"] == "User: hello"


def test_ingest_otlp_spans_merges_with_tier1_turns(
    db_session,
    org_id,
    default_workspace,
):
    call_short_id = "123456"
    result = EvaluatorResult(
        id=uuid4(),
        result_id="900002",
        organization_id=org_id,
        workspace_id=default_workspace.id,
        evaluator_id=uuid4(),
        agent_id=uuid4(),
        name="Phone test",
        status=EvaluatorResultStatus.QUEUED.value,
    )
    db_session.add(result)
    db_session.commit()

    trace = open_trace(
        db_session,
        organization_id=org_id,
        workspace_id=default_workspace.id,
        evaluator_result_id=result.id,
        agent_id=result.agent_id,
        call_short_id=call_short_id,
        transport="phone",
        tier="black_box",
    )

    from app.models.database import SyntheticTracePayload
    from app.services.synthetic_traces.trace_service import record_tier1_turns

    record_tier1_turns(
        db_session,
        trace,
        [{"turn_number": 1, "sut_response_latency_ms": 850.0}],
    )

    trace, _accepted, correlated = ingest_otlp_spans(
        db_session,
        organization_id=org_id,
        spans=[
            {
                "trace_id": "def",
                "span_id": "llm-1",
                "name": "llm",
                "attributes": {
                    "efficientai.call_short_id": call_short_id,
                    "turn.number": 1,
                    "gen_ai.operation.name": "chat",
                    "metrics.ttfb": 0.4,
                },
            }
        ],
        header_call_short_id=call_short_id,
    )

    assert correlated is True
    assert trace.tier == "mixed"

    payload = (
        db_session.query(SyntheticTracePayload)
        .filter(SyntheticTracePayload.synthetic_call_trace_id == trace.id)
        .first()
    )
    assert payload.turns[0]["sut_response_latency_ms"] == 850.0
    assert payload.turns[0]["llm_ttfb_ms"] == 400.0


def test_backfill_creates_trace_from_vobiz_call_recording(
    db_session,
    org_id,
    default_workspace,
):
    result = EvaluatorResult(
        id=uuid4(),
        result_id="900003",
        organization_id=org_id,
        workspace_id=default_workspace.id,
        evaluator_id=uuid4(),
        agent_id=uuid4(),
        name="Phone test",
        status=EvaluatorResultStatus.COMPLETED.value,
    )
    db_session.add(result)
    db_session.commit()

    recording = CallRecording(
        organization_id=org_id,
        workspace_id=default_workspace.id,
        call_short_id="555555",
        status=CallRecordingStatus.UPDATED,
        source=CallRecordingSource.WEBHOOK,
        call_event="call_ended",
        call_data={"ended_at": "2026-08-31T12:00:00Z"},
        provider_platform="vobiz",
        evaluator_result_id=result.id,
    )
    db_session.add(recording)
    db_session.commit()

    created = backfill_missing_traces_from_call_recordings(
        db_session, organization_id=org_id, workspace_id=default_workspace.id
    )
    assert created == 1

    rows, total = list_traces(
        db_session,
        organization_id=org_id,
        workspace_id=uuid4(),
    )
    assert total == 0

    rows, total = list_traces(
        db_session,
        organization_id=org_id,
        workspace_id=default_workspace.id,
    )
    assert total == 1
    assert rows[0].evaluator_result_id == result.id
    assert rows[0].status == "closed"


def test_backfill_does_not_create_traces_for_other_workspaces(
    db_session,
    org_id,
    default_workspace,
):
    other_workspace_id = uuid4()
    result_other = EvaluatorResult(
        id=uuid4(),
        result_id="900099",
        organization_id=org_id,
        workspace_id=other_workspace_id,
        evaluator_id=uuid4(),
        agent_id=uuid4(),
        name="Other workspace phone test",
        status=EvaluatorResultStatus.COMPLETED.value,
    )
    db_session.add(result_other)
    db_session.commit()

    recording_other = CallRecording(
        organization_id=org_id,
        workspace_id=other_workspace_id,
        call_short_id="666666",
        status=CallRecordingStatus.UPDATED,
        source=CallRecordingSource.WEBHOOK,
        call_event="call_ended",
        call_data={"ended_at": "2026-08-31T12:00:00Z"},
        provider_platform="vobiz",
        evaluator_result_id=result_other.id,
    )
    db_session.add(recording_other)
    db_session.commit()

    created = backfill_missing_traces_from_call_recordings(
        db_session,
        organization_id=org_id,
        workspace_id=default_workspace.id,
    )
    assert created == 0

    trace = (
        db_session.query(SyntheticCallTrace)
        .filter(SyntheticCallTrace.evaluator_result_id == result_other.id)
        .first()
    )
    assert trace is None


def test_ingest_otlp_spans_prefers_span_call_short_id_over_stale_header(
    db_session,
    org_id,
    default_workspace,
):
    first = open_trace_session(
        db_session,
        organization_id=org_id,
        workspace_id=default_workspace.id,
        transport="webrtc",
    )
    second = open_trace_session(
        db_session,
        organization_id=org_id,
        workspace_id=default_workspace.id,
        transport="webrtc",
    )

    trace, accepted, correlated = ingest_otlp_spans(
        db_session,
        organization_id=org_id,
        spans=[_stt_span(second.call_short_id)],
        header_call_short_id=first.call_short_id,
        workspace_id=default_workspace.id,
    )
    assert accepted == 1
    assert correlated is True
    assert trace is not None
    assert trace.call_short_id == second.call_short_id
    assert trace.turn_count == 1
    assert first.turn_count == 0


def test_open_trace_session_mint_ingest_and_close(
    db_session,
    org_id,
    default_workspace,
):
    trace = open_trace_session(
        db_session,
        organization_id=org_id,
        workspace_id=default_workspace.id,
        transport="websocket",
    )
    assert trace.call_short_id
    assert trace.transport == "websocket"
    assert trace.tier == "component"
    assert trace.status == "open"

    call_short_id = trace.call_short_id
    ingested, accepted, correlated = ingest_otlp_spans(
        db_session,
        organization_id=org_id,
        spans=[_stt_span(call_short_id)],
        header_call_short_id=call_short_id,
        workspace_id=default_workspace.id,
    )
    assert ingested is not None
    assert accepted == 1
    assert correlated is True

    closed = close_trace_session(
        db_session,
        organization_id=org_id,
        call_short_id=call_short_id,
        workspace_id=default_workspace.id,
    )
    assert closed is not None
    assert closed.status == "closed"


def test_maybe_auto_close_open_trace_after_idle(db_session, org_id, default_workspace):
    from datetime import timedelta

    from app.models.database import SyntheticCallTrace
    from app.services.synthetic_traces.trace_service import (
        maybe_auto_close_open_trace,
        open_trace_session,
        record_tier1_turns,
    )

    trace = open_trace_session(
        db_session,
        organization_id=org_id,
        workspace_id=default_workspace.id,
        transport="webrtc",
    )
    record_tier1_turns(
        db_session,
        trace,
        [{"turn_number": 1, "sut_response_latency_ms": 500.0}],
    )
    row = db_session.get(SyntheticCallTrace, trace.id)
    row.updated_at = row.updated_at - timedelta(seconds=130)
    db_session.commit()

    closed = maybe_auto_close_open_trace(db_session, row)
    assert closed.status == "closed"
    assert closed.ended_at is not None


def test_ingest_json_spans(
    db_session,
    org_id,
    default_workspace,
):
    trace = open_trace_session(
        db_session,
        organization_id=org_id,
        workspace_id=default_workspace.id,
        transport="custom",
    )
    call_short_id = trace.call_short_id

    ingested, accepted, correlated = ingest_json_spans(
        db_session,
        organization_id=org_id,
        workspace_id=default_workspace.id,
        call_short_id=call_short_id,
        spans=[
            {"name": "llm", "turn_number": 1, "ttfb_ms": 250},
        ],
    )
    assert accepted == 1
    assert correlated is True
    assert ingested is not None
    assert ingested.turn_count == 1
