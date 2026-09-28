import pytest
from fastapi import HTTPException

from app.models.enums import ChatConnectionTypeEnum, ChatEvalModeEnum, CallMediumEnum
from app.services.agents.chat_preprod_scope import (
    apply_preprod_chat_create,
    apply_preprod_chat_update,
    assert_preprod_chat_connection_allowed,
    assert_preprod_chat_eval_mode_allowed,
)
from app.services.agents.chat_connection import validate_chat_connection_for_agent


class _ChatAgentPayload:
    def __init__(self, **kwargs):
        self.call_medium = kwargs.get("call_medium", CallMediumEnum.CHAT)
        self.chat_connection_type = kwargs.get("chat_connection_type")
        self.chat_eval_mode = kwargs.get("chat_eval_mode")


def test_assert_preprod_rejects_post_prod_eval_mode():
    with pytest.raises(HTTPException) as exc:
        assert_preprod_chat_eval_mode_allowed(ChatEvalModeEnum.POST_PROD_IMPORT)
    assert exc.value.status_code == 400


def test_assert_preprod_rejects_non_internal_connection():
    with pytest.raises(HTTPException) as exc:
        assert_preprod_chat_connection_allowed(ChatConnectionTypeEnum.CUSTOMER_API)
    assert exc.value.status_code == 400


def test_apply_preprod_chat_create_normalizes_internal_llm():
    payload = _ChatAgentPayload(
        chat_connection_type=ChatConnectionTypeEnum.INTERNAL_LLM,
        chat_eval_mode=None,
    )
    apply_preprod_chat_create(payload)
    assert payload.chat_eval_mode == ChatEvalModeEnum.PRE_PROD_SIM
    assert payload.chat_connection_type == ChatConnectionTypeEnum.INTERNAL_LLM


def test_apply_preprod_chat_update_forces_eval_mode():
    update = {"chat_eval_mode": "post_prod_live"}
    apply_preprod_chat_update(update, db_call_medium=CallMediumEnum.CHAT)
    assert update["chat_eval_mode"] == "pre_prod_sim"


def test_validate_chat_connection_internal_llm_requires_main_llm():
    from types import SimpleNamespace

    agent = SimpleNamespace(
        chat_connection_type="internal_llm",
        main_llm_provider="",
        main_llm_model="",
        voice_bundle_id=None,
        test_llm_provider="openai",
        test_llm_model="gpt-4o-mini",
    )
    err = validate_chat_connection_for_agent(agent)
    assert err is not None
    assert "main_llm" in err.lower()
