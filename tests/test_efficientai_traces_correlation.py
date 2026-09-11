"""Tests for EfficientAI trace correlation helpers."""

from efficientai.integrations.efficientai_traces.correlation import (
    build_outbound_sip_headers,
    extract_call_short_id,
    format_plivo_sip_headers,
    otlp_export_headers,
    span_correlation_attributes,
)


def test_extract_call_short_id_from_vobiz_sip_header():
    cid = extract_call_short_id(
        sip_headers={"X-VH-EfficientAI-Call-Short-Id": "482931"},
    )
    assert cid == "482931"


def test_extract_call_short_id_from_plivo_prefixed_header():
    cid = extract_call_short_id(
        sip_headers={"X-PH-EfficientAI-Call-Short-Id": "123456"},
    )
    assert cid == "123456"


def test_build_outbound_sip_headers_includes_vobiz_and_plivo_keys():
    headers = build_outbound_sip_headers(
        call_short_id="482931",
        evaluator_result_id="f1d04e90-bae5-4e1b-bbaa-60b2fd7b692f",
    )
    assert headers["X-VH-EfficientAI-Call-Short-Id"] == "482931"
    assert headers["EfficientAI-Call-Short-Id"] == "482931"
    assert "X-VH-EfficientAI-Run-Id" in headers
    plivo = format_plivo_sip_headers(headers)
    assert "X-VH-EfficientAI-Call-Short-Id=482931" in plivo


def test_otlp_export_headers_uses_call_short_id():
    headers = otlp_export_headers(api_key="secret", call_short_id="482931")
    assert headers["X-API-Key"] == "secret"
    assert headers["X-EfficientAI-Call-Short-Id"] == "482931"


def test_extract_call_short_id_from_env_style_webhook_param():
    cid = extract_call_short_id(
        webhook_params={"SipHeader_X-VH-EfficientAI-Call-Short-Id": "654321"},
    )
    assert cid == "654321"


def test_span_correlation_attributes_includes_workspace_id():
    attrs = span_correlation_attributes(
        call_short_id="482931",
        agent_id="agent-1",
        workspace_id="ws-1",
    )
    assert attrs["efficientai.workspace_id"] == "ws-1"
    assert attrs["efficientai.call_short_id"] == "482931"


def test_parse_trace_handshake_full_and_legacy():
    from efficientai.integrations.efficientai_traces.handshake import parse_trace_handshake

    full = parse_trace_handshake(
        {
            "type": "efficientai_trace_handshake",
            "call_short_id": "482931",
            "agent_id": "a1",
            "workspace_id": "w1",
            "otel_correlation": {"otlp_endpoint": "http://localhost:8000/x"},
        }
    )
    assert full is not None
    assert full["call_short_id"] == "482931"
    assert full["agent_id"] == "a1"

    legacy = parse_trace_handshake({"efficientai_call_short_id": "123456"})
    assert legacy is not None
    assert legacy["call_short_id"] == "123456"
