"""Persist chat_connection_config with optional secret encryption."""

from __future__ import annotations

from typing import Any, Optional

from app.core.encryption import decrypt_api_key, encrypt_api_key


def prepare_chat_connection_config_for_storage(
    config: Optional[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    if not config or not isinstance(config, dict):
        return config
    out = dict(config)
    secret_keys = (
        "api_auth_value",
        "meta_whatsapp_access_token",
        "whatsapp_access_token",
        "twilio_auth_token",
    )
    for key in secret_keys:
        auth = out.get(key)
        if isinstance(auth, str) and auth.strip():
            plain = decrypt_api_key(auth.strip())
            if plain != auth.strip():
                out[key] = auth.strip()
            else:
                out[key] = encrypt_api_key(plain)
    return out


def chat_connection_config_for_runtime(config: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not config or not isinstance(config, dict):
        return {}
    out = dict(config)
    secret_keys = (
        "api_auth_value",
        "meta_whatsapp_access_token",
        "whatsapp_access_token",
        "twilio_auth_token",
    )
    for key in secret_keys:
        auth = out.get(key)
        if isinstance(auth, str) and auth.strip():
            out[key] = decrypt_api_key(auth.strip())
    return out
