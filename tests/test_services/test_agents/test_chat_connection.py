from app.models.enums import ChatConnectionTypeEnum
from app.services.agents.chat_connection import coerce_chat_connection_type


def test_coerce_chat_connection_type_enum_member():
    assert coerce_chat_connection_type(ChatConnectionTypeEnum.INTERNAL_LLM) == "internal_llm"


def test_coerce_chat_connection_type_value_string():
    assert coerce_chat_connection_type("internal_llm") == "internal_llm"


def test_coerce_chat_connection_type_legacy_repr_string():
    raw = "ChatConnectionTypeEnum.INTERNAL_LLM"
    assert coerce_chat_connection_type(raw) == "internal_llm"
