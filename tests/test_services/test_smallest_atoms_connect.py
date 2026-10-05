from app.services.agents.smallest_atoms_connect import (
    chat_websocket_uri,
    parse_inbound_event,
)


def test_parse_inbound_event_nested():
    event = parse_inbound_event(
        '{"data": {"type": "transcript", "role": "assistant", "text": "Hi"}}'
    )
    assert event is not None
    assert event.get("type") == "transcript"


def test_chat_websocket_uri_mode_chat():
    uri = chat_websocket_uri("sk_test_key", "agent-99")
    assert "mode=chat" in uri
    assert "agent_id=agent-99" in uri
    assert "token=sk_test_key" in uri
    assert uri.startswith("wss://api.smallest.ai/atoms/v1/agent/connect?")
