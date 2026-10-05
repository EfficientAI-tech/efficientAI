"""Tests for voice provider registry and prompt sync helper."""

import importlib
from types import SimpleNamespace

from app.services.voice_providers import get_voice_provider
from app.services.voice_providers.retell import RetellVoiceProvider
from app.services.voice_providers.smallest import SmallestVoiceProvider
from app.services.voice_providers.vapi import VapiVoiceProvider

prompt_sync_module = importlib.import_module("app.services.voice_providers.prompt_sync")


def test_get_voice_provider_returns_expected_classes():
    assert get_voice_provider("retell") is RetellVoiceProvider
    assert get_voice_provider("VAPI") is VapiVoiceProvider
    assert get_voice_provider("SMALLEST") is SmallestVoiceProvider


def test_sync_provider_prompt_updates_agent_and_commits(monkeypatch):
    class _Provider:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def extract_agent_prompt(self, _agent_id, *, agent_channel=None):
            return "hello provider prompt"

    class _DB:
        def __init__(self):
            self.commits = 0

        def commit(self):
            self.commits += 1

    monkeypatch.setattr(prompt_sync_module, "decrypt_api_key", lambda _v: "decrypted-key")
    monkeypatch.setattr(prompt_sync_module, "get_voice_provider", lambda _p: _Provider)

    db = _DB()
    agent = SimpleNamespace(
        name="Agent-1",
        voice_ai_agent_id="voice-agent-id",
        provider_prompt=None,
        provider_prompt_synced_at=None,
    )
    integration = SimpleNamespace(platform="retell", api_key="enc-key", public_key=None)

    prompt = prompt_sync_module.sync_provider_prompt(agent=agent, integration=integration, db=db)

    assert prompt == "hello provider prompt"
    assert agent.provider_prompt == "hello provider prompt"
    assert agent.provider_prompt_synced_at is not None
    assert db.commits == 1


def test_build_voice_provider_passes_elevenlabs_base_url(monkeypatch):
    captured = {}

    class _Provider:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(prompt_sync_module, "get_voice_provider", lambda _p: _Provider)

    integration = SimpleNamespace(
        platform="elevenlabs",
        api_key="enc-key",
        public_key=None,
        api_base_url="https://api.eu.residency.elevenlabs.io",
    )
    prompt_sync_module.build_voice_provider_from_integration(integration, decrypted_key="plain")

    assert captured == {
        "api_key": "plain",
        "base_url": "https://api.eu.residency.elevenlabs.io",
    }


def test_build_voice_provider_omits_base_url_when_unset(monkeypatch):
    captured = {}

    class _Provider:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(prompt_sync_module, "get_voice_provider", lambda _p: _Provider)

    integration = SimpleNamespace(
        platform="elevenlabs",
        api_key="enc-key",
        public_key=None,
        api_base_url=None,
    )
    prompt_sync_module.build_voice_provider_from_integration(integration, decrypted_key="plain")

    assert captured == {"api_key": "plain"}
