from cryptography.fernet import Fernet

from app.core import encryption
from app.models.enums import ChatConnectionTypeEnum
from app.services.agents.chat_connection import coerce_chat_connection_type
from app.services.agents.chat_connection_config_store import (
    prepare_chat_connection_config_for_storage,
)


def test_coerce_chat_connection_type_enum_member():
    assert coerce_chat_connection_type(ChatConnectionTypeEnum.INTERNAL_LLM) == "internal_llm"


def test_coerce_chat_connection_type_value_string():
    assert coerce_chat_connection_type("internal_llm") == "internal_llm"


def test_coerce_chat_connection_type_legacy_repr_string():
    raw = "ChatConnectionTypeEnum.INTERNAL_LLM"
    assert coerce_chat_connection_type(raw) == "internal_llm"


def test_prepare_chat_config_encrypts_long_meta_whatsapp_token(monkeypatch):
    key = Fernet.generate_key()
    fernet = Fernet(key)
    monkeypatch.setattr(encryption, "_fernet_instance", None)
    monkeypatch.setattr(encryption, "get_fernet", lambda: fernet)

    meta_token = "EAA" + ("x" * 200)
    stored = prepare_chat_connection_config_for_storage(
        {"meta_whatsapp_access_token": meta_token},
    )
    assert stored is not None
    assert stored["meta_whatsapp_access_token"].startswith("gAAAAA")
    assert encryption.decrypt_api_key(stored["meta_whatsapp_access_token"]) == meta_token
