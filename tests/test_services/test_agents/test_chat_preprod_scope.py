import pytest
from fastapi import HTTPException

from app.models.enums import ChatConnectionTypeEnum, ChatEvalModeEnum, CallMediumEnum
from app.services.agents.chat_preprod_scope import (
    apply_preprod_chat_create,
    apply_preprod_chat_update,
    assert_chat_eval_import_disabled,
    default_chat_eval_mode_for_connection,
)
from app.services.agents.chat_connection import validate_chat_connection_for_agent


class _ChatAgentPayload:
    def __init__(self, **kwargs):
        self.call_medium = kwargs.get("call_medium", CallMediumEnum.CHAT)
        self.chat_connection_type = kwargs.get("chat_connection_type")
        self.chat_eval_mode = kwargs.get("chat_eval_mode")


def test_default_eval_mode_by_connection():
    assert default_chat_eval_mode_for_connection(ChatConnectionTypeEnum.INTERNAL_LLM) == "pre_prod_sim"
    assert default_chat_eval_mode_for_connection(ChatConnectionTypeEnum.PROVIDER_CHAT) == "post_prod_live"
    assert default_chat_eval_mode_for_connection(ChatConnectionTypeEnum.CUSTOMER_API) == "post_prod_live"


def test_assert_chat_eval_import_disabled():
    with pytest.raises(HTTPException) as exc:
        assert_chat_eval_import_disabled(ChatEvalModeEnum.POST_PROD_IMPORT)
    assert exc.value.status_code == 400


def test_apply_preprod_chat_create_customer_api_live():
    payload = _ChatAgentPayload(
        chat_connection_type=ChatConnectionTypeEnum.CUSTOMER_API,
        chat_eval_mode=None,
    )
    apply_preprod_chat_create(payload)
    assert payload.chat_eval_mode == ChatEvalModeEnum.POST_PROD_LIVE
    assert payload.chat_connection_type == ChatConnectionTypeEnum.CUSTOMER_API


def test_apply_preprod_chat_update_keeps_live_mode():
    update = {"chat_eval_mode": "pre_prod_sim"}
    apply_preprod_chat_update(
        update,
        db_call_medium=CallMediumEnum.CHAT,
        db_connection_type="customer_api",
    )
    assert update["chat_eval_mode"] == "post_prod_live"


def test_provider_chat_always_uses_live_production_leg():
    from types import SimpleNamespace
    from app.services.agents.chat_production_leg import uses_live_production_leg

    agent = SimpleNamespace(
        chat_eval_mode="pre_prod_sim",
        chat_connection_type="provider_chat",
        call_medium="chat",
        voice_ai_integration_id="00000000-0000-0000-0000-000000000001",
        voice_ai_agent_id="vapi-1",
        chat_connection_config=None,
        main_llm_provider="together",
        main_llm_model="meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
    )
    assert uses_live_production_leg(agent) is True


def test_normalized_chat_eval_mode_defaults_provider_chat_to_live():
    from types import SimpleNamespace
    from app.services.agents.chat_production_leg import normalized_chat_eval_mode

    agent = SimpleNamespace(
        chat_eval_mode=None,
        chat_connection_type="provider_chat",
        call_medium="chat",
        voice_ai_integration_id="00000000-0000-0000-0000-000000000001",
        voice_ai_agent_id="vapi-1",
        main_llm_provider="",
        main_llm_model="",
        chat_connection_config=None,
    )
    assert normalized_chat_eval_mode(agent) == "post_prod_live"


def test_normalized_connection_infers_provider_chat_even_with_main_llm_fields():
    from types import SimpleNamespace
    from app.services.agents.chat_connection import normalized_chat_connection_type

    agent = SimpleNamespace(
        call_medium="chat",
        chat_connection_type=None,
        voice_ai_integration_id="00000000-0000-0000-0000-000000000001",
        voice_ai_agent_id="vapi-agent-1",
        main_llm_provider="together",
        main_llm_model="meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
        chat_connection_config=None,
    )
    assert normalized_chat_connection_type(agent) == "provider_chat"


def test_normalized_chat_eval_mode_upgrades_stale_pre_prod_on_provider_chat():
    from types import SimpleNamespace
    from app.services.agents.chat_production_leg import normalized_chat_eval_mode

    agent = SimpleNamespace(
        chat_eval_mode="pre_prod_sim",
        chat_connection_type="provider_chat",
        call_medium="chat",
        voice_ai_integration_id="00000000-0000-0000-0000-000000000001",
        voice_ai_agent_id="vapi-1",
        main_llm_provider="together",
        main_llm_model="meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
        chat_connection_config=None,
    )
    assert normalized_chat_eval_mode(agent) == "post_prod_live"


def test_stored_messaging_connection_type_not_overridden_by_platform_link():
    from types import SimpleNamespace
    from app.services.agents.chat_connection import normalized_chat_connection_type

    agent = SimpleNamespace(
        call_medium="chat",
        chat_connection_type="messaging_channels",
        voice_ai_integration_id="00000000-0000-0000-0000-000000000001",
        voice_ai_agent_id="vapi-agent-1",
        chat_connection_config={"messaging_channel": "whatsapp"},
        main_llm_provider="",
        main_llm_model="",
    )
    assert normalized_chat_connection_type(agent) == "messaging_channels"


def test_stored_internal_llm_not_upgraded_by_leftover_api_url():
    from types import SimpleNamespace
    from app.services.agents.chat_connection import normalized_chat_connection_type

    agent = SimpleNamespace(
        call_medium="chat",
        chat_connection_type="internal_llm",
        voice_ai_integration_id=None,
        voice_ai_agent_id=None,
        chat_connection_config={"api_base_url": "https://example.com/chat"},
        main_llm_provider="openai",
        main_llm_model="gpt-4.1-nano",
    )
    assert normalized_chat_connection_type(agent) == "internal_llm"


def test_normalized_connection_infers_provider_chat_from_platform_link():
    from types import SimpleNamespace
    from app.services.agents.chat_connection import normalized_chat_connection_type

    agent = SimpleNamespace(
        call_medium="chat",
        chat_connection_type=None,
        voice_ai_integration_id="00000000-0000-0000-0000-000000000001",
        voice_ai_agent_id="vapi-agent-1",
        main_llm_provider="",
        main_llm_model="",
        chat_connection_config=None,
    )
    assert normalized_chat_connection_type(agent) == "provider_chat"


def test_validate_chat_connection_provider_chat_without_agent_llm():
    from types import SimpleNamespace

    agent = SimpleNamespace(
        chat_connection_type="provider_chat",
        voice_ai_integration_id="00000000-0000-0000-0000-000000000001",
        voice_ai_agent_id="agent-123",
        provider_prompt="You are a helpful chat agent for billing support.",
        description="",
        main_llm_provider="",
        main_llm_model="",
        test_llm_provider="",
        test_llm_model="",
        voice_bundle_id=None,
    )
    assert validate_chat_connection_for_agent(agent) is None


def test_validate_chat_connection_customer_api_without_agent_llm():
    from types import SimpleNamespace

    agent = SimpleNamespace(
        chat_connection_type="customer_api",
        chat_connection_config={"api_base_url": "https://example.com"},
        main_llm_provider="",
        main_llm_model="",
        test_llm_provider="",
        test_llm_model="",
        voice_bundle_id=None,
    )
    assert validate_chat_connection_for_agent(agent) is None
