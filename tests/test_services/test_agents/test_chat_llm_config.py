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
