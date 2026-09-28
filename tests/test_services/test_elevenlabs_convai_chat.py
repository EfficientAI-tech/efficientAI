"""ElevenLabs ConvAI text chat WebSocket helpers."""

from app.services.agents.elevenlabs_convai_chat import (
    _extract_agent_text_from_event,
    _handle_ping,
)


def test_extract_agent_response_event():
    text = _extract_agent_text_from_event(
        {
            "type": "agent_response",
            "agent_response_event": {"agent_response": "Hello, how can I help?"},
        }
    )
    assert text == "Hello, how can I help?"


def test_extract_agent_chat_response_part_nested():
    text = _extract_agent_text_from_event(
        {
            "type": "agent_chat_response_part",
            "text_response_part": {"type": "delta", "text": "Hi there"},
        }
    )
    assert text == "Hi there"


def test_handle_ping_sends_pong():
    sent: list[str] = []

    class _Ws:
        def send(self, payload: str) -> None:
            sent.append(payload)

    _handle_ping(_Ws(), {"type": "ping", "ping_event": {"event_id": 42}})
    assert sent == ['{"type": "pong", "event_id": 42}']
