import json
from unittest.mock import MagicMock, patch

from app.services.agents.customer_websocket_chat import call_customer_websocket_chat
from app.services.agents.provider_platform_chat import ProviderChatState


@patch("app.services.agents.customer_websocket_chat.websockets.sync.client.connect")
def test_customer_websocket_turn(mock_connect):
    ws = MagicMock()
    mock_connect.return_value = ws
    ws.recv.return_value = json.dumps({"reply": "pong"})

    state = ProviderChatState()
    text = call_customer_websocket_chat(
        {
            "websocket_url": "wss://example.com/chat",
        },
        transcript=[{"speaker": "Speaker 1", "text": "hi"}],
        agent_name="Bot",
        language="en",
        state=state,
    )
    assert text == "pong"
    ws.send.assert_called_once()
    mock_connect.assert_called_once()
