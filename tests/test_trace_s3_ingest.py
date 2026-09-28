"""Tests for S3-first OTLP WAL ingest (ClickHouse path)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.services.synthetic_traces.ingest_pipeline import (
    IngestUnavailable,
    ingest_otlp_batch_to_s3,
    resolve_trace_uuid_for_s3_ingest,
)


def _otlp_json_body(call_short_id: str) -> bytes:
    payload = {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "abc",
                                "spanId": "s1",
                                "name": "stt",
                                "attributes": [
                                    {
                                        "key": "efficientai.call_short_id",
                                        "value": {"stringValue": call_short_id},
                                    }
                                ],
                            }
                        ]
                    }
                ]
            }
        ]
    }
    return json.dumps(payload).encode()


@patch("app.services.synthetic_traces.clickhouse_store.mint_trace_uuid")
def test_resolve_trace_uuid_mints_when_no_hint(mock_mint, db_session, org_id, default_workspace):
    new_id = uuid4()
    mock_mint.return_value = new_id
    resolved = resolve_trace_uuid_for_s3_ingest(
        db_session,
        organization_id=org_id,
        workspace_id=default_workspace.id,
    )
    assert resolved == new_id


@patch("app.services.synthetic_traces.ingest_pipeline.schedule_s3_batch_process")
@patch("app.services.storage.blob_storage_service.blob_storage_service.upload_file_by_key")
@patch("app.services.synthetic_traces.clickhouse_store.next_batch_seq", return_value=1)
@patch("app.services.synthetic_traces.ingest_pipeline.resolve_trace_uuid_for_s3_ingest")
def test_ingest_otlp_batch_to_s3_puts_and_enqueues(
    mock_resolve,
    mock_seq,
    mock_upload,
    mock_schedule,
    db_session,
    org_id,
    default_workspace,
):
    trace_id = uuid4()
    mock_resolve.return_value = trace_id
    body = _otlp_json_body("482931")

    result = ingest_otlp_batch_to_s3(
        db_session,
        organization_id=org_id,
        workspace_id=default_workspace.id,
        body=body,
        content_type="application/json",
        header_call_short_id="482931",
    )

    assert result["trace_uuid"] == trace_id
    assert result["accepted_bytes"] == len(body)
    mock_upload.assert_called_once()
    mock_schedule.assert_called_once()


@patch(
    "app.services.storage.blob_storage_service.blob_storage_service.upload_file_by_key",
    side_effect=RuntimeError("s3 down"),
)
@patch("app.services.synthetic_traces.clickhouse_store.next_batch_seq", return_value=1)
@patch("app.services.synthetic_traces.ingest_pipeline.resolve_trace_uuid_for_s3_ingest", return_value=uuid4())
def test_ingest_otlp_batch_to_s3_raises_on_s3_failure(
    _resolve,
    _seq,
    _upload,
    db_session,
    org_id,
    default_workspace,
):
    with pytest.raises(IngestUnavailable):
        ingest_otlp_batch_to_s3(
            db_session,
            organization_id=org_id,
            workspace_id=default_workspace.id,
            body=b"{}",
            content_type="application/json",
        )
