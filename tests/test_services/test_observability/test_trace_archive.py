from unittest.mock import patch
from uuid import UUID

from app.services.observability.trace_archive import load_provider_trace, persist_provider_trace


@patch("app.services.observability.trace_archive.s3_service")
def test_persist_provider_trace_inline(mock_s3_service):
    mock_s3_service.is_enabled.return_value = False
    updated = persist_provider_trace(
        call_data={"status": "ended"},
        provider_platform="retell",
        organization_id=UUID("00000000-0000-0000-0000-000000000001"),
        call_short_id="abc123",
        trace_payload={
            "trace_id": "retell-call_123",
            "root_span_id": "root",
            "spans": [{"span_id": "root", "name": "conversation"}],
            "trace_source": "retell_synthetic",
        },
        source="retell_synthetic",
    )

    provider_trace = updated["provider_trace"]
    assert provider_trace["storage"] == "inline"
    assert provider_trace["trace_source"] == "retell_synthetic"
    assert updated["trace_id"] == "retell-call_123"
    assert isinstance(provider_trace.get("normalized_trace"), dict)


@patch("app.services.observability.trace_archive.s3_service")
def test_persist_provider_trace_archives_large_payload(mock_s3_service):
    mock_s3_service.is_enabled.return_value = True
    mock_s3_service.prefix = "efficientai/"
    mock_s3_service.upload_file_by_key.return_value = "key"
    mock_s3_service.download_file_by_key.return_value = (
        b'{"trace_payload":{"trace_id":"el-1","root_span_id":"root","spans":[{"span_id":"root","name":"conversation"}],'
        b'"trace_source":"elevenlabs"}}'
    )

    updated = persist_provider_trace(
        call_data={"status": "done"},
        provider_platform="elevenlabs",
        organization_id=UUID("00000000-0000-0000-0000-000000000001"),
        call_short_id="el123",
        trace_payload={
            "trace_id": "el-1",
            "root_span_id": "root",
            "spans": [{"span_id": "root", "name": "conversation"}],
            "trace_source": "elevenlabs",
        },
        source="elevenlabs_post_call_webhook",
        raw_payload={"resourceSpans": [{"x": "y" * 5000}]},
        inline_limit_bytes=64,
    )

    provider_trace = updated["provider_trace"]
    assert provider_trace["storage"] == "s3"
    assert isinstance(provider_trace.get("trace_s3_key"), str)

    loaded = load_provider_trace(updated)
    assert loaded is not None
    assert loaded["trace_id"] == "el-1"
