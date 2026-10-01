"""agent_kind=chat routing per platform in integration agent picker."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.voice_providers import voice_agent_catalog as catalog


def _integration(platform: str):
    return SimpleNamespace(
        id="00000000-0000-0000-0000-000000000099",
        platform=SimpleNamespace(value=platform),
    )


@pytest.mark.parametrize("platform", ["vapi", "elevenlabs", "smallest"])
def test_chat_kind_uses_list_agents_for_unified_platforms(monkeypatch, platform):
    provider = MagicMock()
    provider.list_agents.return_value = [{"id": "a1", "name": "Unified Bot"}]
    provider.last_list_truncated = False
    provider.list_chat_agents = MagicMock(side_effect=AssertionError("should not call list_chat_agents"))

    monkeypatch.setattr(catalog, "_build_voice_provider", lambda _i: provider)

    result = catalog.list_integration_voice_agents(
        _integration(platform),
        refresh=True,
        agent_kind="chat",
    )

    provider.list_agents.assert_called_once()
    assert result.agents == [{"id": "a1", "name": "Unified Bot"}]
    assert result.message and "same agent" in result.message.lower()


def test_chat_kind_uses_retell_list_chat_agents(monkeypatch):
    provider = MagicMock()
    provider.list_chat_agents.return_value = [
        {"id": "chat_1", "name": "Chat Agent"},
    ]
    provider.list_agents = MagicMock(side_effect=AssertionError("should not call list_agents"))

    monkeypatch.setattr(catalog, "_build_voice_provider", lambda _i: provider)

    result = catalog.list_integration_voice_agents(
        _integration("retell"),
        refresh=True,
        agent_kind="chat",
    )

    provider.list_chat_agents.assert_called_once()
    assert result.agents[0]["id"] == "chat_1"


def test_voice_kind_uses_list_agents_for_retell(monkeypatch):
    provider = MagicMock()
    provider.list_agents.return_value = [{"id": "voice_1", "name": "Voice Bot"}]

    monkeypatch.setattr(catalog, "_build_voice_provider", lambda _i: provider)

    catalog.list_integration_voice_agents(
        _integration("retell"),
        refresh=True,
        agent_kind="voice",
    )

    provider.list_agents.assert_called_once()
