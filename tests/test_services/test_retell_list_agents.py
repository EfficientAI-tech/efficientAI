"""Retell agent list parsing (SDK v5 paginated response)."""

from app.services.voice_providers.retell import RetellVoiceProvider, _retell_agent_list_page


def test_retell_agent_list_page_from_dict():
    items, has_more, key = _retell_agent_list_page(
        {
            "items": [{"agent_id": "agent_abc", "agent_name": "Reception"}],
            "has_more": True,
            "pagination_key": "next",
        }
    )
    assert len(items) == 1
    assert has_more is True
    assert key == "next"


def test_retell_list_agents_reads_items(monkeypatch):
    captured = {}

    class _FakeAgentAPI:
        def list(self, **kwargs):
            captured.update(kwargs)
            return {
                "items": [
                    {"agent_id": "agent_1", "agent_name": "Test Bot"},
                ],
                "has_more": False,
            }

    class _FakeClient:
        agent = _FakeAgentAPI()

    provider = RetellVoiceProvider.__new__(RetellVoiceProvider)
    provider.client = _FakeClient()

    agents = provider.list_agents()
    assert agents == [{"id": "agent_1", "name": "Test Bot"}]
    assert captured.get("filter_criteria") == {
        "channel": {"type": "string", "op": "eq", "value": "voice"},
    }


def test_retell_list_chat_agents_uses_channel_filter(monkeypatch):
    captured = {}

    class _FakeAgentAPI:
        def list(self, **kwargs):
            captured.update(kwargs)
            return {
                "items": [
                    {"agent_id": "chat_1", "agent_name": "Chat Bot"},
                ],
                "has_more": False,
            }

    class _FakeClient:
        agent = _FakeAgentAPI()

    provider = RetellVoiceProvider.__new__(RetellVoiceProvider)
    provider.client = _FakeClient()

    agents = provider.list_chat_agents()
    assert agents == [{"id": "chat_1", "name": "Chat Bot"}]
    assert captured.get("filter_criteria") == {
        "channel": {"type": "string", "op": "eq", "value": "chat"},
    }
