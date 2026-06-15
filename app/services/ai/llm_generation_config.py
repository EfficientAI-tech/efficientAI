"""Helpers for merging and applying user LLM generation parameters."""

from __future__ import annotations

from typing import Any, Dict, Optional


def merge_llm_config(
    primary: Optional[Dict[str, Any]] = None,
    *,
    legacy_temperature: Optional[float] = None,
    legacy_max_tokens: Optional[int] = None,
) -> Dict[str, Any]:
    """Merge ``llm_config`` JSON with legacy VoiceBundle columns.

    Legacy ``llm_temperature`` / ``llm_max_tokens`` apply only when the
    corresponding key is absent from ``primary``.
    """
    merged: Dict[str, Any] = dict(primary or {})
    if merged.get("temperature") is None and legacy_temperature is not None:
        merged["temperature"] = legacy_temperature
    if merged.get("max_tokens") is None and legacy_max_tokens is not None:
        merged["max_tokens"] = legacy_max_tokens
    return merged


def resolve_effective_llm_config(
    *,
    llm_config: Optional[Dict[str, Any]] = None,
    override_llm_config: Optional[Dict[str, Any]] = None,
    legacy_temperature: Optional[float] = None,
    legacy_max_tokens: Optional[int] = None,
    task_defaults: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Resolve config with override > entity > legacy columns > task defaults."""
    base = merge_llm_config(
        llm_config,
        legacy_temperature=legacy_temperature,
        legacy_max_tokens=legacy_max_tokens,
    )
    if override_llm_config:
        for key, value in override_llm_config.items():
            if value is not None:
                base[key] = value

    effective = dict(task_defaults or {})
    for key, value in base.items():
        if value is not None:
            effective[key] = value
    return effective


def build_litellm_kwargs(
    *,
    llm_config: Optional[Dict[str, Any]] = None,
    override_llm_config: Optional[Dict[str, Any]] = None,
    legacy_temperature: Optional[float] = None,
    legacy_max_tokens: Optional[int] = None,
    task_defaults: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build kwargs for :meth:`LLMService.generate_response`.

    Returns a dict with ``temperature``, ``max_tokens``, and ``config``
    (extra LiteLLM params such as top_p / top_k / penalties).
    """
    effective = resolve_effective_llm_config(
        llm_config=llm_config,
        override_llm_config=override_llm_config,
        legacy_temperature=legacy_temperature,
        legacy_max_tokens=legacy_max_tokens,
        task_defaults=task_defaults,
    )

    temperature = effective.pop("temperature", (task_defaults or {}).get("temperature", 0.7))
    max_tokens = effective.pop("max_tokens", (task_defaults or {}).get("max_tokens"))
    extra = {k: v for k, v in effective.items() if v is not None}
    return {
        "temperature": temperature,
        "max_tokens": max_tokens,
        "config": extra or None,
    }


def build_efficientai_input_params(provider: str, config: Optional[Dict[str, Any]]):
    """Map merged config dict to the EfficientAI SDK InputParams for *provider*."""
    if not config:
        return None

    provider_key = (provider or "").lower()
    params_dict = {
        k: v
        for k, v in {
            "temperature": config.get("temperature"),
            "top_p": config.get("top_p"),
            "top_k": config.get("top_k"),
            "max_tokens": config.get("max_tokens"),
            "frequency_penalty": config.get("frequency_penalty"),
            "presence_penalty": config.get("presence_penalty"),
            "seed": config.get("seed"),
        }.items()
        if v is not None
    }
    if not params_dict:
        return None

    if provider_key == "openai":
        from efficientai.services.openai.llm import OpenAILLMService

        return OpenAILLMService.InputParams(**params_dict)
    if provider_key == "google":
        from efficientai.services.google.llm import GoogleLLMService

        return GoogleLLMService.InputParams(**params_dict)
    if provider_key == "anthropic":
        from efficientai.services.anthropic.llm import AnthropicLLMService

        return AnthropicLLMService.InputParams(**params_dict)

    return None
