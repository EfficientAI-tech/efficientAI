"""End-to-end readiness checks for every chat connection type used in evaluator runs."""

from types import SimpleNamespace

import pytest

from app.models.enums import ChatConnectionTypeEnum, ChatEvalModeEnum, CallMediumEnum
from app.services.agents.chat_connection import validate_chat_connection_for_agent
from app.services.agents.chat_llm_config import agent_has_chat_simulation_config, should_use_llm_text_simulation
from app.services.agents.chat_production_leg import normalized_chat_eval_mode, uses_live_production_leg


def _chat_agent(**kwargs) -> SimpleNamespace:
    base = dict(
        call_medium=CallMediumEnum.CHAT.value,
        chat_eval_mode=ChatEvalModeEnum.POST_PROD_LIVE.value,
        test_llm_provider="openai",
        test_llm_model="gpt-4.1-nano",
        test_llm_credential_id=None,
        main_llm_provider="openai",
        main_llm_model="gpt-4.1-nano",
        main_llm_credential_id=None,
        voice_bundle_id=None,
        voice_ai_integration_id=None,
        voice_ai_agent_id=None,
        provider_prompt="You are a helpful billing support chat agent for customers.",
        description="",
        chat_connection_config={},
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


@pytest.mark.parametrize(
    "conn_type,extra,expect_live",
    [
        (ChatConnectionTypeEnum.INTERNAL_LLM.value, {}, False),
        (
            ChatConnectionTypeEnum.PROVIDER_CHAT.value,
            {
                "voice_ai_integration_id": "00000000-0000-0000-0000-000000000001",
                "voice_ai_agent_id": "agent-1",
            },
            True,
        ),
        (
            ChatConnectionTypeEnum.CUSTOMER_API.value,
            {"chat_connection_config": {"api_base_url": "https://example.com/chat"}},
            True,
        ),
        (
            ChatConnectionTypeEnum.CUSTOMER_WEBSOCKET.value,
            {"chat_connection_config": {"websocket_url": "wss://example.com/ws"}},
            True,
        ),
        (
            ChatConnectionTypeEnum.MESSAGING_CHANNELS.value,
            {"chat_connection_config": {"messaging_channel": "sms"}},
            True,
        ),
    ],
)
def test_live_production_leg_by_connection_type(conn_type, extra, expect_live):
    agent = _chat_agent(chat_connection_type=conn_type, **extra)
    if conn_type == ChatConnectionTypeEnum.INTERNAL_LLM.value:
        agent.chat_eval_mode = ChatEvalModeEnum.PRE_PROD_SIM.value
    assert uses_live_production_leg(agent) is expect_live


@pytest.mark.parametrize(
    "conn_type,extra",
    [
        (
            ChatConnectionTypeEnum.PROVIDER_CHAT.value,
            {
                "voice_ai_integration_id": "00000000-0000-0000-0000-000000000001",
                "voice_ai_agent_id": "agent-1",
            },
        ),
        (
            ChatConnectionTypeEnum.CUSTOMER_API.value,
            {"chat_connection_config": {"api_base_url": "https://example.com/chat"}},
        ),
        (
            ChatConnectionTypeEnum.CUSTOMER_WEBSOCKET.value,
            {"chat_connection_config": {"websocket_url": "wss://example.com/ws"}},
        ),
        (
            ChatConnectionTypeEnum.MESSAGING_CHANNELS.value,
            {"chat_connection_config": {"messaging_channel": "whatsapp"}},
        ),
        (
            ChatConnectionTypeEnum.INTERNAL_LLM.value,
            {"chat_eval_mode": ChatEvalModeEnum.PRE_PROD_SIM.value},
        ),
    ],
)
def test_validate_passes_when_required_fields_present(conn_type, extra):
    agent = _chat_agent(chat_connection_type=conn_type, **extra)
    assert validate_chat_connection_for_agent(agent) is None
    assert agent_has_chat_simulation_config(agent) is True
    assert (
        should_use_llm_text_simulation(
            agent,
            has_voice_bundle=False,
            has_voice_ai_integration=bool(agent.voice_ai_integration_id),
        )
        is True
    )


def test_internal_llm_requires_main_llm():
    agent = _chat_agent(
        chat_connection_type=ChatConnectionTypeEnum.INTERNAL_LLM.value,
        chat_eval_mode=ChatEvalModeEnum.PRE_PROD_SIM.value,
        main_llm_provider="",
        main_llm_model="",
    )
    err = validate_chat_connection_for_agent(agent)
    assert err is not None
    assert "main LLM" in err or "chat agent LLM" in err


def test_messaging_requires_channel():
    agent = _chat_agent(
        chat_connection_type=ChatConnectionTypeEnum.MESSAGING_CHANNELS.value,
        chat_connection_config={},
    )
    err = validate_chat_connection_for_agent(agent)
    assert err is not None
    assert "messaging_channel" in err


def test_provider_chat_eval_mode_is_live():
    agent = _chat_agent(
        chat_connection_type=ChatConnectionTypeEnum.PROVIDER_CHAT.value,
        chat_eval_mode=ChatEvalModeEnum.PRE_PROD_SIM.value,
        voice_ai_integration_id="00000000-0000-0000-0000-000000000001",
        voice_ai_agent_id="agent-1",
    )
    assert normalized_chat_eval_mode(agent) == ChatEvalModeEnum.POST_PROD_LIVE.value
