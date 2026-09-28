"""Pre-prod rollout scope for LLM chat agents (post-prod paths disabled in product)."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException, status

from app.models.enums import CallMediumEnum, ChatConnectionTypeEnum, ChatEvalModeEnum

PREPROD_CHAT_CONNECTION = ChatConnectionTypeEnum.INTERNAL_LLM
PREPROD_CHAT_EVAL_MODE = ChatEvalModeEnum.PRE_PROD_SIM


def is_chat_call_medium(call_medium: Any) -> bool:
    if call_medium is None:
        return False
    raw = call_medium.value if hasattr(call_medium, "value") else call_medium
    return str(raw).lower() == CallMediumEnum.CHAT.value


def preprod_chat_eval_mode_value() -> str:
    return PREPROD_CHAT_EVAL_MODE.value


def _connection_type_value(conn: Any) -> str:
    if conn is None:
        return PREPROD_CHAT_CONNECTION.value
    if hasattr(conn, "value"):
        return str(conn.value).lower()
    return str(conn).lower()


def assert_preprod_chat_connection_allowed(conn: Any) -> None:
    if _connection_type_value(conn) != PREPROD_CHAT_CONNECTION.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Chat agents currently support pre-prod simulation with Platform LLM only "
                "(chat_connection_type=internal_llm). Other connection types are not enabled yet."
            ),
        )


def assert_preprod_chat_eval_mode_allowed(requested: Any) -> None:
    if requested is None:
        return
    raw = requested.value if hasattr(requested, "value") else requested
    if str(raw).lower() != PREPROD_CHAT_EVAL_MODE.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Chat eval mode must be pre_prod_sim during pre-prod rollout. "
                "Post-prod live and import modes are not enabled yet."
            ),
        )


def apply_preprod_chat_create(agent_payload: Any) -> None:
    """Validate and normalize chat fields on agent create."""
    if not is_chat_call_medium(getattr(agent_payload, "call_medium", None)):
        return
    assert_preprod_chat_eval_mode_allowed(getattr(agent_payload, "chat_eval_mode", None))
    conn = getattr(agent_payload, "chat_connection_type", None) or PREPROD_CHAT_CONNECTION
    assert_preprod_chat_connection_allowed(conn)
    agent_payload.chat_eval_mode = PREPROD_CHAT_EVAL_MODE
    agent_payload.chat_connection_type = PREPROD_CHAT_CONNECTION


def apply_preprod_chat_update(
    update_data: dict[str, Any],
    *,
    db_call_medium: Any,
) -> None:
    """Force pre-prod chat eval mode on agent update."""
    effective_medium = update_data.get("call_medium", db_call_medium)
    if not is_chat_call_medium(effective_medium):
        return
    update_data["chat_eval_mode"] = preprod_chat_eval_mode_value()
    if "chat_connection_type" in update_data and update_data["chat_connection_type"] is not None:
        assert_preprod_chat_connection_allowed(update_data["chat_connection_type"])
