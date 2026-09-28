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


def test_validate_chat_connection_internal_llm_accepts_test_llm_only():
    from types import SimpleNamespace

    agent = SimpleNamespace(
        chat_connection_type="internal_llm",
        main_llm_provider="",
        main_llm_model="",
        voice_bundle_id=None,
        test_llm_provider="openai",
        test_llm_model="gpt-4o-mini",
    )
    assert validate_chat_connection_for_agent(agent) is None
