"""Strip dangerous LiteLLM overrides from client-supplied config."""

from __future__ import annotations

from typing import Any, Dict, Optional, Set

_BLOCKED_LLM_CONFIG_KEYS: Set[str] = {
    "api_base",
    "api_key",
    "api_version",
    "base_url",
    "azure_endpoint",
    "azure_ad_token",
    "aws_access_key_id",
    "aws_secret_access_key",
    "aws_region_name",
    "extra_headers",
    "headers",
    "authorization",
    "litellm_proxy_api_key",
    "proxy",
    "custom_llm_provider",
    "model",
    "model_id",
}

_ALLOWED_LLM_CONFIG_KEYS: Set[str] = {
    "temperature",
    "max_tokens",
    "top_p",
    "top_k",
    "frequency_penalty",
    "presence_penalty",
    "seed",
    "stop",
    "n",
    "response_format",
    "timeout",
}


def sanitize_client_llm_config(
    config: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not config:
        return None
    sanitized: Dict[str, Any] = {}
    for key, value in config.items():
        normalized = str(key).strip().lower()
        if normalized in _BLOCKED_LLM_CONFIG_KEYS:
            continue
        if normalized not in _ALLOWED_LLM_CONFIG_KEYS:
            continue
        if value is not None:
            sanitized[key] = value
    return sanitized or None
