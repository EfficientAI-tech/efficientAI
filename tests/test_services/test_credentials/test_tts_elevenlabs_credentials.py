"""TTS ElevenLabs key and regional URL must come from the same credential source."""

from uuid import uuid4

from app.core.encryption import encrypt_api_key
from app.models.database import AIProvider, Integration, ModelProvider
from app.services.ai.tts_service import TTSService


def test_tts_pairs_integration_key_with_integration_base_url(db_session, org_id, seed_org, monkeypatch):
    regional = Integration(
        id=uuid4(),
        organization_id=org_id,
        platform="elevenlabs",
        api_key=encrypt_api_key("regional-key"),
        name="ElevenLabs EU",
        is_active=True,
        is_default=True,
        api_base_url="https://api.eu.elevenlabs.io",
    )
    other = Integration(
        id=uuid4(),
        organization_id=org_id,
        platform="elevenlabs",
        api_key=encrypt_api_key("other-key"),
        name="ElevenLabs US",
        is_active=True,
        is_default=False,
        api_base_url="https://api.us.elevenlabs.io",
    )
    db_session.add_all([regional, other])
    db_session.commit()

    captured = {}

    def _fake_elevenlabs(_text, _model, api_key, _voice=None, _config=None, base_url=None):
        captured["api_key"] = api_key
        captured["base_url"] = base_url
        return (b"audio", 1.0)

    service = TTSService()
    monkeypatch.setattr(service, "_synthesize_with_elevenlabs", _fake_elevenlabs)

    service.synthesize(
        text="hello",
        tts_provider=ModelProvider.ELEVENLABS,
        tts_model="eleven_turbo_v2",
        organization_id=org_id,
        db=db_session,
    )

    assert captured["api_key"] == "regional-key"
    assert captured["base_url"] == "https://api.eu.elevenlabs.io"


def test_tts_aiprovider_key_does_not_use_integration_base_url(db_session, org_id, seed_org, monkeypatch):
    db_session.add(
        AIProvider(
            id=uuid4(),
            organization_id=org_id,
            provider="elevenlabs",
            api_key=encrypt_api_key("ai-provider-key"),
            name="ElevenLabs AIProvider",
            is_active=True,
            is_default=True,
        )
    )
    db_session.add(
        Integration(
            id=uuid4(),
            organization_id=org_id,
            platform="elevenlabs",
            api_key=encrypt_api_key("integration-key"),
            name="ElevenLabs Integration",
            is_active=True,
            is_default=True,
            api_base_url="https://api.eu.elevenlabs.io",
        )
    )
    db_session.commit()

    captured = {}

    def _fake_elevenlabs(_text, _model, api_key, _voice=None, _config=None, base_url=None):
        captured["api_key"] = api_key
        captured["base_url"] = base_url
        return (b"audio", 1.0)

    service = TTSService()
    monkeypatch.setattr(service, "_synthesize_with_elevenlabs", _fake_elevenlabs)

    service.synthesize(
        text="hello",
        tts_provider=ModelProvider.ELEVENLABS,
        tts_model="eleven_turbo_v2",
        organization_id=org_id,
        db=db_session,
    )

    assert captured["api_key"] == "ai-provider-key"
    assert "base_url" not in captured or captured.get("base_url") is None
