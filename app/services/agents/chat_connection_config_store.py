"""Persist chat_connection_config with optional secret encryption."""

from __future__ import annotations

from typing import Any, Optional

from app.core.encryption import decrypt_api_key, encrypt_api_key

CHAT_CONFIG_SECRET_MASK = "••••••••"
_SECRET_KEYS = (
    "api_auth_value",
    "meta_whatsapp_access_token",
    "whatsapp_access_token",
    "twilio_auth_token",
)


def _is_masked_secret(value: str) -> bool:
    text = value.strip()
    return not text or text == CHAT_CONFIG_SECRET_MASK


def mask_chat_connection_config_for_response(
    config: Optional[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    if not config or not isinstance(config, dict):
        return config
    out = dict(config)
    for key in _SECRET_KEYS:
        if isinstance(out.get(key), str) and out[key].strip():
            out[key] = CHAT_CONFIG_SECRET_MASK
    return out


def prepare_chat_connection_config_for_storage(
    config: Optional[dict[str, Any]],
    *,
    previous: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    if not config or not isinstance(config, dict):
        return config
    out = dict(config)
    prev = previous if isinstance(previous, dict) else {}
    for key in _SECRET_KEYS:
        auth = out.get(key)
        if not isinstance(auth, str):
            continue
        if _is_masked_secret(auth):
            if key in prev:
                out[key] = prev[key]
            else:
                out.pop(key, None)
            continue
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
    for key in _SECRET_KEYS:
        auth = out.get(key)
        if isinstance(auth, str) and auth.strip():
            out[key] = decrypt_api_key(auth.strip())
    return out
