from types import SimpleNamespace
from uuid import uuid4

from app.models.database import AIProvider, VoiceBundle
from app.models.enums import CallMediumEnum, ModelProvider
from app.services.agents.chat_llm_config import (
    _resolve_org_default_simulation_llm,
    resolve_simulation_llm,
)


def test_org_default_maps_retired_together_enabled_model(db_session):
    org_id = uuid4()
    row = SimpleNamespace(
        id=uuid4(),
        provider=ModelProvider.TOGETHER.value,
        is_default=True,
        gateway_model="",
    )

    from app.models.database import AIProvider

    provider = AIProvider(
        id=row.id,
        organization_id=org_id,
        provider=row.provider,
        api_key="enc",
        is_active=True,
        is_default=True,
        enabled_models=["meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo"],
    )
    db_session.add(provider)
    db_session.commit()

    resolved = _resolve_org_default_simulation_llm(db_session, org_id)
    assert resolved is not None
    assert resolved.model == "meta-llama/Llama-3.2-3B-Instruct-Turbo"
    assert resolved.source == "org_default_test_llm"


def test_chat_test_leg_prefers_voice_bundle_over_org_default(db_session, org_id):
    bundle = VoiceBundle(
        organization_id=org_id,
        name="test",
        bundle_type="stt_llm_tts",
        stt_provider="sarvam",
        stt_model="saaras:v3",
        llm_provider=ModelProvider.OPENAI.value,
        llm_model="gpt-4.1-nano",
        tts_provider="sarvam",
        tts_model="bulbul:v3",
        is_active=True,
    )
    db_session.add(bundle)
    together = AIProvider(
        organization_id=org_id,
        provider=ModelProvider.TOGETHER.value,
        api_key="enc",
        is_active=True,
        is_default=True,
        enabled_models=["meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo"],
    )
    db_session.add(together)
    db_session.commit()
    db_session.refresh(bundle)

    agent = SimpleNamespace(
        call_medium=CallMediumEnum.CHAT.value,
        voice_bundle_id=bundle.id,
        test_llm_provider=None,
        test_llm_model=None,
        test_llm_credential_id=None,
        test_llm_config=None,
        main_llm_provider=None,
        main_llm_model=None,
    )

    resolved = resolve_simulation_llm(db_session, agent=agent, organization_id=org_id, leg="test")
    assert resolved.provider == ModelProvider.OPENAI
    assert resolved.model == "gpt-4.1-nano"
    assert resolved.source == "voice_bundle_test_caller"
