from unittest.mock import MagicMock, patch

from app.services.agents.chat_messaging_turn_wait import (
    complete_twilio_sms_turn,
    register_twilio_sms_turn,
    wait_twilio_sms_reply,
)


@patch("app.services.agents.chat_messaging_turn_wait._redis")
def test_register_and_complete_turn(mock_redis_fn):
    client = MagicMock()
    mock_redis_fn.return_value = client
    client.get.return_value = "turn-1"

    turn_id = register_twilio_sms_turn(twilio_from="+15550001", messaging_recipient="+15550002")
    assert turn_id

    ok = complete_twilio_sms_turn(
        twilio_to="+15550001",
        reply_from="+15550002",
        body="Hello back",
    )
    assert ok is True
    client.rpush.assert_called()


@patch("app.services.agents.chat_messaging_turn_wait._redis")
def test_wait_returns_body(mock_redis_fn):
    client = MagicMock()
    mock_redis_fn.return_value = client
    client.blpop.return_value = ("key", "agent reply")

    assert wait_twilio_sms_reply("turn-abc", timeout_secs=2) == "agent reply"


@patch("app.services.agents.chat_messaging_turn_wait._redis")
def test_complete_turn_when_twilio_to_differs_from_configured_from(mock_redis_fn):
    client = MagicMock()
    mock_redis_fn.return_value = client

    def fake_get(key: str):
        if "pending:from:+15550002:+15550001" in key or "pending:from:+15550002:" in key:
            return "turn-1"
        return None

    client.get.side_effect = fake_get

    ok = complete_twilio_sms_turn(
        twilio_to="56161703",
        reply_from="+15550002",
        body="5",
    )
    assert ok is True
    client.rpush.assert_called()
