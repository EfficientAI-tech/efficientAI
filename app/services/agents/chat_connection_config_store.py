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
    "websocket_auth_value",
)


def _is_masked_secret(value: str) -> bool:
    text = value.strip()
    return not text or text == CHAT_CONFIG_SECRET_MASK


def _is_fernet_ciphertext(value: str) -> bool:
    return value.strip().startswith("gAAAAA")


def _secret_value_for_storage(value: str) -> str:
    """Encrypt plaintext secrets; pass through ciphertext encrypted with this deployment key."""
    stripped = value.strip()
    if _is_fernet_ciphertext(stripped):
        plain = decrypt_api_key(stripped)
        if plain != stripped:
            return stripped
    return encrypt_api_key(stripped)


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


def enrich_chat_connection_config_for_storage(
    config: Optional[dict[str, Any]],
    *,
    connection_type: Optional[str] = None,
    previous: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Apply defaults (e.g. Twilio inbound webhook token) before encrypting secrets."""
    if not config or not isinstance(config, dict):
        return config
    out = dict(config)
    prev = previous if isinstance(previous, dict) else {}
    conn = (connection_type or "").strip().lower()
    channel = (out.get("messaging_channel") or prev.get("messaging_channel") or "").strip().lower()
    if conn == "messaging_channels" and channel in ("sms", "whatsapp"):
        if prev.get("twilio_inbound_webhook_token") and not out.get("twilio_inbound_webhook_token"):
            out["twilio_inbound_webhook_token"] = prev["twilio_inbound_webhook_token"]
    return prepare_chat_connection_config_for_storage(out, previous=previous)


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
        out[key] = _secret_value_for_storage(auth)
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
