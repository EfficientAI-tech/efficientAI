from app.services.agents.chat_outbound_payload import (
    customer_api_request_body,
    messaging_webhook_request_body,
    trim_transcript,
)


def test_customer_api_omits_transcript_by_default():
    body = customer_api_request_body(
        {},
        openai_messages=[{"role": "user", "content": "hi"}],
        transcript=[{"speaker": "Speaker 1", "text": "hi"}],
        agent_name="A",
        language="en",
    )
    assert "messages" in body
    assert "transcript" not in body


def test_customer_api_includes_transcript_when_opted_in():
    body = customer_api_request_body(
        {"include_full_transcript": True},
        openai_messages=[],
        transcript=[{"speaker": "Speaker 1", "text": "x"}],
        agent_name="A",
        language="en",
    )
    assert body["transcript"] == [{"speaker": "Speaker 1", "text": "x"}]


def test_trim_transcript_keeps_tail():
    rows = [{"speaker": "Speaker 1", "text": str(i)} for i in range(50)]
    trimmed = trim_transcript(rows, max_messages=10)
    assert len(trimmed) == 10
    assert trimmed[0]["text"] == "40"


def test_messaging_webhook_includes_latest_user_message():
    body = messaging_webhook_request_body(
        transcript=[
            {"speaker": "Speaker 1", "text": "old"},
            {"speaker": "Speaker 2", "text": "reply"},
            {"speaker": "Speaker 1", "text": "new question"},
        ],
        channel="sms",
        sender_id="+1",
    )
    assert body["latest_user_message"] == "new question"
    assert len(body["messages"]) == 3
