"""Playground STT must pair ElevenLabs regional URLs with Integration keys only."""

import importlib
from types import SimpleNamespace
from uuid import uuid4

playground_module = importlib.import_module("app.api.v1.routes.playground")


def test_resolve_agent_stt_config_ai_provider_key_ignores_integration_base_url(monkeypatch):
    org_id = uuid4()
    agent_id = uuid4()
    bundle_id = uuid4()

    agent = SimpleNamespace(id=agent_id, organization_id=org_id, voice_bundle_id=bundle_id)
    voice_bundle = SimpleNamespace(
        id=bundle_id,
        organization_id=org_id,
        stt_provider=SimpleNamespace(value="elevenlabs"),
        stt_model="scribe_v2",
        stt_credential_id=uuid4(),
    )
    ai_prov = SimpleNamespace(
        organization_id=org_id,
        provider="elevenlabs",
        is_active=True,
        api_key="enc-ai",
    )

    class _Query:
        def __init__(self, model):
            self.model = model

        def filter(self, *args, **kwargs):
            return self

        def first(self):
            if self.model.__name__ == "Agent":
                return agent
            if self.model.__name__ == "VoiceBundle":
                return voice_bundle
            if self.model.__name__ == "AIProvider":
                return ai_prov
            return None

    db = SimpleNamespace(query=lambda model: _Query(model))
    monkeypatch.setattr(playground_module, "decrypt_api_key", lambda _v: "ai-key")

    _provider, _model, api_key, api_base_url = playground_module._resolve_agent_stt_config(
        str(agent_id), org_id, db
    )

    assert api_key == "ai-key"
    assert api_base_url is None
