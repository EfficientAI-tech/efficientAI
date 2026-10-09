from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.enums import CallMediumEnum, ModelProvider
from app.services.agents.chat_llm_config import resolve_simulation_llm


def test_chat_test_leg_requires_explicit_test_llm(db_session, org_id):
    agent = SimpleNamespace(
        call_medium=CallMediumEnum.CHAT.value,
        test_llm_provider=None,
        test_llm_model=None,
        test_llm_credential_id=None,
        test_llm_config=None,
        main_llm_provider=None,
        main_llm_model=None,
    )

    with pytest.raises(ValueError, match="test-agent LLM"):
        resolve_simulation_llm(db_session, agent=agent, organization_id=org_id, leg="test")


def test_chat_test_leg_uses_agent_fields(db_session, org_id):
    agent = SimpleNamespace(
        call_medium=CallMediumEnum.CHAT.value,
        test_llm_provider=ModelProvider.OPENAI.value,
        test_llm_model="gpt-4.1-nano",
        test_llm_credential_id=uuid4(),
        test_llm_config=None,
        main_llm_provider=None,
        main_llm_model=None,
    )

    resolved = resolve_simulation_llm(db_session, agent=agent, organization_id=org_id, leg="test")
    assert resolved.provider == ModelProvider.OPENAI
    assert resolved.model == "gpt-4.1-nano"
    assert resolved.source == "test_llm"


def test_voice_agent_falls_back_to_voice_bundle(db_session, org_id, seed_org):
    from app.models.database import VoiceBundle

    bundle_id = uuid4()
    bundle = VoiceBundle(
        id=bundle_id,
        organization_id=org_id,
        name="Bundle",
        bundle_type="stt_llm_tts",
        stt_provider="openai",
        stt_model="whisper-1",
        llm_provider=ModelProvider.OPENAI.value,
        llm_model="gpt-4o-mini",
        tts_provider="openai",
        tts_model="gpt-4o-mini-tts",
    )
    db_session.add(bundle)
    db_session.commit()

    agent = SimpleNamespace(
        call_medium=CallMediumEnum.PHONE_CALL.value,
        voice_bundle_id=bundle_id,
        test_llm_provider=None,
        test_llm_model=None,
        test_llm_credential_id=None,
        test_llm_config=None,
        main_llm_provider=None,
        main_llm_model=None,
    )

    resolved = resolve_simulation_llm(db_session, agent=agent, organization_id=org_id, leg="test")
    assert resolved.source == "voice_bundle"
    assert resolved.model == "gpt-4o-mini"


def test_messaging_main_uses_test_llm_when_main_unset(db_session, org_id):
    agent = SimpleNamespace(
        call_medium=CallMediumEnum.CHAT.value,
        chat_connection_type="messaging_channels",
        chat_connection_config={"messaging_channel": "whatsapp"},
        test_llm_provider=ModelProvider.OPENAI.value,
        test_llm_model="gpt-4.1-nano",
        test_llm_credential_id=uuid4(),
        test_llm_config=None,
        main_llm_provider=None,
        main_llm_model=None,
        voice_bundle_id=None,
    )

    resolved = resolve_simulation_llm(db_session, agent=agent, organization_id=org_id, leg="main")
    assert resolved.source == "test_llm_for_messaging_production"
    assert resolved.model == "gpt-4.1-nano"
