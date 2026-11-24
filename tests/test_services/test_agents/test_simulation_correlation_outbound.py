"""Simulation turns send the platform call id to the agent under test."""

import json
from unittest.mock import MagicMock, patch

from app.services.agents.customer_api_chat import call_customer_chat_api
from app.services.agents.customer_websocket_chat import call_customer_websocket_chat
from app.services.agents.provider_platform_chat import ProviderChatState
from app.services.synthetic_traces.simulation_outbound import (
    correlation_http_headers,
    handshake_enabled,
    trace_handshake_message,
)


def test_correlation_headers_and_handshake():
    correlation = {
        "call_short_id": "165730",
        "evaluator_result_id": "run-1",
        "agent_id": "agent-1",
        "workspace_id": "ws-1",
        "transport": "websocket",
    }
    assert correlation_http_headers(correlation) == {
        "X-EfficientAI-Call-Short-Id": "165730",
        "X-EfficientAI-Run-Id": "run-1",
    }
    message = trace_handshake_message(correlation)
    assert message["type"] == "efficientai_trace_handshake"
    assert message["call_short_id"] == "165730"
    assert message["otel_correlation"]["suggested_span_attributes"]["efficientai.evaluator_result_id"] == "run-1"
    assert handshake_enabled({}) is True
    assert handshake_enabled({"efficientai_trace_handshake_enabled": False}) is False
    assert handshake_enabled({"efficientai_trace_handshake_enabled": "off"}) is False


@patch("app.services.agents.chat_outbound_urls.assert_chat_connection_urls_safe")
@patch("app.services.telephony.recording_download.assert_outbound_http_url_safe")
@patch("app.services.agents.customer_api_chat.httpx.Client")
def test_customer_chat_api_sends_correlation_headers(mock_client_cls, _mock_host, _mock_urls):
    response = MagicMock()
    response.json.return_value = {"reply": "ok"}
    response.raise_for_status.return_value = None
    client = MagicMock()
    client.post.return_value = response
    client.__enter__.return_value = client
    mock_client_cls.return_value = client

    call_customer_chat_api(
        {"api_base_url": "https://agent.example", "api_message_path": "/chat"},
        transcript=[],
        agent_name="Agent",
        language="en",
        extra_headers={
            "X-EfficientAI-Call-Short-Id": "165730",
            "X-EfficientAI-Run-Id": "run-1",
        },
    )
    headers = client.post.call_args.kwargs["headers"]
    assert headers["X-EfficientAI-Call-Short-Id"] == "165730"
    assert headers["X-EfficientAI-Run-Id"] == "run-1"


@patch("app.services.agents.customer_websocket_chat.websockets.sync.client.connect")
def test_customer_websocket_sends_handshake_before_the_turn(mock_connect):
    ws = MagicMock()
    mock_connect.return_value = ws
    ws.recv.return_value = json.dumps({"reply": "pong"})
    handshake = {"type": "efficientai_trace_handshake", "call_short_id": "165730"}

    call_customer_websocket_chat(
        {"websocket_url": "wss://example.com/chat"},
        transcript=[{"speaker": "Speaker 1", "text": "hi"}],
        agent_name="Bot",
        language="en",
        state=ProviderChatState(),
        extra_headers={"X-EfficientAI-Call-Short-Id": "165730"},
        handshake=handshake,
    )

    connect_headers = mock_connect.call_args.kwargs["additional_headers"]
    assert connect_headers["X-EfficientAI-Call-Short-Id"] == "165730"
    first_send, second_send = (call.args[0] for call in ws.send.call_args_list)
    assert json.loads(first_send) == handshake
    assert "hi" in second_send


@patch("app.services.agents.customer_websocket_chat.websockets.sync.client.connect")
def test_customer_websocket_can_skip_the_handshake(mock_connect):
    ws = MagicMock()
    mock_connect.return_value = ws
    ws.recv.return_value = json.dumps({"reply": "pong"})

    call_customer_websocket_chat(
        {"websocket_url": "wss://example.com/chat"},
        transcript=[{"speaker": "Speaker 1", "text": "hi"}],
        agent_name="Bot",
        language="en",
        state=ProviderChatState(),
        handshake=None,
    )
    assert ws.send.call_count == 1
