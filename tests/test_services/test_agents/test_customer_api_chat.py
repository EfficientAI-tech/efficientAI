import pytest

from app.services.agents.customer_api_chat import call_customer_chat_api


def test_customer_api_rejects_absolute_message_path():
    with pytest.raises(ValueError, match="relative path"):
        call_customer_chat_api(
            {
                "api_base_url": "https://api.example.com",
                "api_message_path": "https://evil.example/steal",
            },
            transcript=[],
            agent_name="Agent",
            language="en",
        )
