"""Tests for Layout 3 staged OTLP ingest."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

from app.models.database import SyntheticTraceIngestStaging, SyntheticTraceSpanBatch
from app.services.synthetic_traces.ingest_pipeline import (
    STAGING_STATUS_FAILED,
    STAGING_STATUS_PROCESSED,
    get_staging_status,
    process_staged_otlp,
    stage_otlp_ingest,
    sweep_staging_ingest,
)
from app.services.synthetic_traces.trace_service import open_trace_session


def _otlp_json_body(call_short_id: str, span_id: str = "s1") -> bytes:
    payload = {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "abc",
                                "spanId": span_id,
                                "name": "stt",
                                "attributes": [
                                    {
                                        "key": "efficientai.call_short_id",
                                        "value": {"stringValue": call_short_id},
                                    },
                                    {
                                        "key": "gen_ai.operation.name",
                                        "value": {"stringValue": "stt"},
                                    },
                                ],
                            }
                        ]
                    }
                ]
            }
        ]
    }
    return json.dumps(payload).encode()


@patch("app.services.synthetic_traces.ingest_pipeline.schedule_staged_process")
def test_stage_otlp_ingest_persists_row(
    mock_schedule,
    db_session,
    org_id,
    default_workspace,
):
    body = _otlp_json_body("482931")
    row = stage_otlp_ingest(
        db_session,
        organization_id=org_id,
        workspace_id=default_workspace.id,
        body=body,
        content_type="application/json",
        header_call_short_id="482931",
    )
    assert row.id is not None
    assert row.body_bytes == len(body)
    assert row.status == "pending"
    mock_schedule.assert_called_once_with(row.id)


@patch("app.services.synthetic_traces.ingest_pipeline.schedule_derive")
def test_process_staged_otlp_parses_and_persists_batch(
    mock_derive,
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
    assert call_short_id

    row = SyntheticTraceIngestStaging(
        organization_id=org_id,
        workspace_id=default_workspace.id,
        content_type="application/json",
        body=_otlp_json_body(call_short_id),
        body_bytes=1,
        header_call_short_id=call_short_id,
        status="pending",
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)

    processed = process_staged_otlp(staging_id=row.id, db=db_session)
    assert processed is not None
    assert processed.status == STAGING_STATUS_PROCESSED
    assert processed.accepted_spans == 1
    assert processed.synthetic_call_trace_id == trace.id
    assert processed.correlated is True

    batches = (
        db_session.query(SyntheticTraceSpanBatch)
        .filter(SyntheticTraceSpanBatch.synthetic_call_trace_id == trace.id)
        .all()
    )
    assert len(batches) == 1
    mock_derive.assert_called_once()


def test_process_staged_otlp_marks_failed_on_bad_payload(
    db_session,
    org_id,
    default_workspace,
):
    row = SyntheticTraceIngestStaging(
        organization_id=org_id,
        workspace_id=default_workspace.id,
        content_type="application/json",
        body=b"not-json",
        body_bytes=8,
        status="pending",
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)

    processed = process_staged_otlp(staging_id=row.id, db=db_session)
    assert processed is not None
    assert processed.status == STAGING_STATUS_FAILED
    assert processed.error_message


def test_get_staging_status_scoped_to_workspace(db_session, org_id, default_workspace):
    row = SyntheticTraceIngestStaging(
        organization_id=org_id,
        workspace_id=default_workspace.id,
        content_type="application/json",
        body=b"{}",
        body_bytes=2,
        status="pending",
    )
    db_session.add(row)
    db_session.commit()

    found = get_staging_status(
        db_session,
        staging_id=row.id,
        organization_id=org_id,
        workspace_id=default_workspace.id,
    )
    assert found is not None

    missing = get_staging_status(
        db_session,
        staging_id=row.id,
        organization_id=org_id,
        workspace_id=uuid4(),
    )
    assert missing is None


def test_sweep_staging_ingest_deletes_old_rows(db_session, org_id, default_workspace):
    old = SyntheticTraceIngestStaging(
        organization_id=org_id,
        workspace_id=default_workspace.id,
        content_type="application/json",
        body=b"{}",
        body_bytes=2,
        status=STAGING_STATUS_PROCESSED,
        processed_at=datetime.now(timezone.utc) - timedelta(hours=72),
    )
    recent = SyntheticTraceIngestStaging(
        organization_id=org_id,
        workspace_id=default_workspace.id,
        content_type="application/json",
        body=b"{}",
        body_bytes=2,
        status=STAGING_STATUS_PROCESSED,
        processed_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    db_session.add_all([old, recent])
    db_session.commit()

    deleted = sweep_staging_ingest(db_session)
    assert deleted == 1
    remaining = db_session.query(SyntheticTraceIngestStaging).all()
    assert len(remaining) == 1
    assert remaining[0].id == recent.id
