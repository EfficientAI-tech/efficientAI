from app.services.agents.smallest_atoms_connect import (
    _credentials_from_response,
    parse_inbound_event,
    resolve_chat_credentials,
)


def test_parse_inbound_event_nested():
    event = parse_inbound_event(
        '{"data": {"type": "transcript", "role": "assistant", "text": "Hi"}}'
    )
    assert event is not None
    assert event.get("type") == "transcript"


def test_credentials_from_response():
    creds = _credentials_from_response(
        {
            "host": "wss://atoms.example.livekit.cloud",
            "token": "jwt-abc",
            "conversationId": "conv-1",
        }
    )
    assert creds is not None
    assert creds.host.startswith("wss://")
    assert creds.access_token == "jwt-abc"
    assert creds.conversation_id == "conv-1"


def test_resolve_chat_credentials_register_call(monkeypatch):
    calls = []

    class FakeProvider:
        def __init__(self, _key):
            pass

        def _request(self, method, path, **kwargs):
            calls.append(path)
            return {
                "host": "wss://lk.smallest.ai",
                "accessToken": "tok-1",
                "callId": "call-9",
            }

    monkeypatch.setattr(
        "app.services.agents.smallest_atoms_connect.SmallestVoiceProvider",
        FakeProvider,
    )
    creds = resolve_chat_credentials("sk", "agent-1")
    assert creds.access_token == "tok-1"
    assert calls[0] == "/conversation/register-call"
