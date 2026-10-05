"""Chat agent eval scope: pre-prod simulation vs post-prod live connections."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.models.enums import CallMediumEnum, ChatConnectionTypeEnum, ChatEvalModeEnum
from app.services.agents.chat_connection import coerce_chat_connection_type

PREPROD_CHAT_CONNECTION = ChatConnectionTypeEnum.INTERNAL_LLM
PREPROD_CHAT_EVAL_MODE = ChatEvalModeEnum.PRE_PROD_SIM
POST_PROD_LIVE_EVAL_MODE = ChatEvalModeEnum.POST_PROD_LIVE

_LIVE_CONNECTIONS = frozenset(
    {
        ChatConnectionTypeEnum.PROVIDER_CHAT.value,
        ChatConnectionTypeEnum.CUSTOMER_API.value,
        ChatConnectionTypeEnum.CUSTOMER_WEBSOCKET.value,
        ChatConnectionTypeEnum.MESSAGING_CHANNELS.value,
    }
)


def is_chat_call_medium(call_medium: Any) -> bool:
    if call_medium is None:
        return False
    raw = call_medium.value if hasattr(call_medium, "value") else call_medium
    return str(raw).lower() == CallMediumEnum.CHAT.value


def _connection_type_value(conn: Any) -> str:
    return coerce_chat_connection_type(conn)


def default_chat_eval_mode_for_connection(conn: Any) -> str:
    if _connection_type_value(conn) == PREPROD_CHAT_CONNECTION.value:
        return PREPROD_CHAT_EVAL_MODE.value
    return POST_PROD_LIVE_EVAL_MODE.value


def assert_chat_eval_import_disabled(requested: Any) -> None:
    if requested is None:
        return
    raw = requested.value if hasattr(requested, "value") else requested
    if str(raw).lower() == ChatEvalModeEnum.POST_PROD_IMPORT.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Post-prod transcript import is not enabled yet. "
                "Use Platform LLM for pre-prod simulation or a live connection type for post-prod."
            ),
        )


def assert_chat_eval_mode_matches_connection(conn: Any, requested: Any) -> None:
    if requested is None:
        return
    expected = default_chat_eval_mode_for_connection(conn)
    raw = requested.value if hasattr(requested, "value") else requested
    if str(raw).lower() != expected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"chat_eval_mode must be {expected} for chat_connection_type="
                f"{_connection_type_value(conn)}."
            ),
        )


def apply_preprod_chat_create(agent_payload: Any) -> None:
    if not is_chat_call_medium(getattr(agent_payload, "call_medium", None)):
        return
    conn = getattr(agent_payload, "chat_connection_type", None) or PREPROD_CHAT_CONNECTION
    assert_chat_eval_import_disabled(getattr(agent_payload, "chat_eval_mode", None))
    assert_chat_eval_mode_matches_connection(conn, getattr(agent_payload, "chat_eval_mode", None))
    agent_payload.chat_connection_type = conn
    agent_payload.chat_eval_mode = default_chat_eval_mode_for_connection(conn)


def apply_preprod_chat_update(
    update_data: dict[str, Any],
    *,
    db_call_medium: Any,
    db_connection_type: Any,
) -> None:
    effective_medium = update_data.get("call_medium", db_call_medium)
    if not is_chat_call_medium(effective_medium):
        return
    assert_chat_eval_import_disabled(update_data.get("chat_eval_mode"))
    conn = update_data.get("chat_connection_type", db_connection_type)
    update_data["chat_eval_mode"] = default_chat_eval_mode_for_connection(conn)
