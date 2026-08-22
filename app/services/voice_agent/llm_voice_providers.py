"""Live voice pipeline LLM provider registry and service factory.

Mirrors the LLM-capable providers exposed in Voice Bundles / Integrations
(see ``app/services/judge_alignment/model_catalog.py``).
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, Optional

from loguru import logger

# Providers selectable for the LLM leg of STT+LLM+TTS voice bundles.
LLM_VOICE_PROVIDER_KEYS = frozenset(
    {
        "openai",
        "anthropic",
        "google",
        "xai",
        "fireworks",
        "cohere",
        "mistral",
        "meta",
        "together",
        "perplexity",
        "azure",
        "aws",
        "openrouter",
        "custom",
        "sarvam",
    }
)

_DEFAULT_LLM_MODELS: Dict[str, str] = {
    "openai": "gpt-4.1",
    "google": "gemini-2.5-flash",
    "anthropic": "claude-sonnet-4.6",
    "xai": "grok-3-beta",
    "fireworks": "accounts/fireworks/models/llama-v3p1-8b-instruct",
    "cohere": "command-r-plus-08-2024",
    "mistral": "mistral-small-latest",
    "meta": "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
    "together": "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
    "perplexity": "sonar",
    "azure": "gpt-4.1",
    "aws": "amazon.nova-lite-v1:0",
    "openrouter": "openai/gpt-4o-2024-11-20",
    "custom": "gpt-4o-mini",
    "sarvam": "sarvam-30b",
}

_ENV_KEYS: Dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "xai": "XAI_API_KEY",
    "fireworks": "FIREWORKS_API_KEY",
    "cohere": "COHERE_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "meta": "TOGETHER_API_KEY",
    "together": "TOGETHER_API_KEY",
    "perplexity": "PERPLEXITY_API_KEY",
    "azure": "AZURE_OPENAI_API_KEY",
    "aws": "AWS_ACCESS_KEY_ID",
    "openrouter": "OPENROUTER_API_KEY",
    "custom": "OPENAI_API_KEY",
    "sarvam": "SARVAM_API_KEY",
}


def normalize_llm_model(provider: str, model: str) -> str:
    """Normalize catalog model ids for provider-specific APIs."""
    provider_key = (provider or "").strip().lower()
    if not model:
        return model
    if provider_key == "fireworks" and not model.startswith("accounts/"):
        return f"accounts/fireworks/models/{model}"
    if provider_key == "azure":
        from app.services.ai.llm_service import _azure_deployment_name

        return _azure_deployment_name(model)
    return model


def default_llm_model(provider: str) -> str:
    return _DEFAULT_LLM_MODELS.get((provider or "").strip().lower(), "gpt-4.1")


def llm_env_key(provider: str) -> str:
    return _ENV_KEYS.get((provider or "").strip().lower(), "OPENAI_API_KEY")


def _parse_aws_credentials(api_key: str) -> Dict[str, Any]:
    """Parse AWS credential JSON or fall back to access key + env secret."""
    try:
        parsed = json.loads(api_key)
        if isinstance(parsed, dict):
            access = (
                parsed.get("aws_access_key_id")
                or parsed.get("access_key_id")
                or parsed.get("aws_access_key")
            )
            secret = (
                parsed.get("aws_secret_access_key")
                or parsed.get("secret_access_key")
                or parsed.get("aws_secret_key")
            )
            return {
                "aws_access_key": access,
                "aws_secret_key": secret,
                "aws_session_token": parsed.get("aws_session_token")
                or parsed.get("session_token"),
                "aws_region": parsed.get("aws_region")
                or parsed.get("region")
                or os.getenv("AWS_REGION", "us-east-1"),
            }
    except (json.JSONDecodeError, TypeError):
        pass
    return {
        "aws_access_key": api_key,
        "aws_secret_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
        "aws_region": os.getenv("AWS_REGION", "us-east-1"),
    }


def get_llm_provider_registry(get_service: Callable[[str], Any]) -> Dict[str, Dict[str, Any]]:
    """Build the LLM provider registry used by ``run_voice_bundle_fastapi``."""

    def _openai_factory(api_key, model, params=None, base_url=None):
        kwargs: Dict[str, Any] = {"api_key": api_key, "model": normalize_llm_model("openai", model)}
        if params:
            kwargs["params"] = params
        if base_url:
            kwargs["base_url"] = base_url
        return get_service("OpenAILLMService")(**kwargs)

    registry: Dict[str, Dict[str, Any]] = {}

    for provider in sorted(LLM_VOICE_PROVIDER_KEYS):
        env_key = llm_env_key(provider)
        default_model = default_llm_model(provider)

        if provider == "openai":
            registry[provider] = {
                "env_key": env_key,
                "default_model": default_model,
                "factory": lambda api_key, model, params=None, _f=_openai_factory: _f(
                    api_key, model, params
                ),
            }
        elif provider == "google":
            registry[provider] = {
                "env_key": env_key,
                "default_model": default_model,
                "factory": lambda api_key, model, params=None, gs=get_service: gs("GoogleLLMService")(
                    api_key=api_key,
                    model=model,
                    **({"params": params} if params else {}),
                ),
            }
        elif provider == "anthropic":
            registry[provider] = {
                "env_key": env_key,
                "default_model": default_model,
                "factory": lambda api_key, model, params=None, gs=get_service: gs("AnthropicLLMService")(
                    api_key=api_key,
                    model=model,
                    **({"params": params} if params else {}),
                ),
            }
        elif provider == "fireworks":
            registry[provider] = {
                "env_key": env_key,
                "default_model": default_model,
                "factory": lambda api_key, model, params=None, gs=get_service: gs("FireworksLLMService")(
                    api_key=api_key,
                    model=normalize_llm_model("fireworks", model),
                    **({"params": params} if params else {}),
                ),
            }
        elif provider == "xai":
            registry[provider] = {
                "env_key": env_key,
                "default_model": default_model,
                "factory": lambda api_key, model, params=None, gs=get_service: gs("GrokLLMService")(
                    api_key=api_key,
                    model=model,
                    **({"params": params} if params else {}),
                ),
            }
        elif provider == "mistral":
            registry[provider] = {
                "env_key": env_key,
                "default_model": default_model,
                "factory": lambda api_key, model, params=None, gs=get_service: gs("MistralLLMService")(
                    api_key=api_key,
                    model=model,
                    **({"params": params} if params else {}),
                ),
            }
        elif provider in ("together", "meta"):
            registry[provider] = {
                "env_key": env_key,
                "default_model": default_model,
                "factory": lambda api_key, model, params=None, gs=get_service: gs("TogetherLLMService")(
                    api_key=api_key,
                    model=model,
                    **({"params": params} if params else {}),
                ),
            }
        elif provider == "perplexity":
            registry[provider] = {
                "env_key": env_key,
                "default_model": default_model,
                "factory": lambda api_key, model, params=None, gs=get_service: gs("PerplexityLLMService")(
                    api_key=api_key,
                    model=model,
                    **({"params": params} if params else {}),
                ),
            }
        elif provider == "openrouter":
            registry[provider] = {
                "env_key": env_key,
                "default_model": default_model,
                "factory": lambda api_key, model, params=None, gs=get_service: gs("OpenRouterLLMService")(
                    api_key=api_key,
                    model=model,
                    **({"params": params} if params else {}),
                ),
            }
        elif provider == "aws":
            registry[provider] = {
                "env_key": env_key,
                "default_model": default_model,
                "factory": lambda api_key, model, params=None, gs=get_service: gs("AWSBedrockLLMService")(
                    model=model,
                    params=params,
                    **_parse_aws_credentials(api_key),
                ),
            }
        elif provider == "cohere":
            registry[provider] = {
                "env_key": env_key,
                "default_model": default_model,
                "factory": lambda api_key, model, params=None, gs=get_service: gs("OpenAILLMService")(
                    api_key=api_key,
                    model=model,
                    base_url="https://api.cohere.com/compatibility/v1",
                    **({"params": params} if params else {}),
                ),
            }
        elif provider == "sarvam":
            registry[provider] = {
                "env_key": env_key,
                "default_model": default_model,
                "factory": lambda api_key, model, params=None, gs=get_service: gs("OpenAILLMService")(
                    api_key=api_key,
                    model=model,
                    base_url="https://api.sarvam.ai/v1",
                    **({"params": params} if params else {}),
                ),
            }
        elif provider == "custom":
            registry[provider] = {
                "env_key": env_key,
                "default_model": default_model,
                "factory": lambda api_key, model, params=None, base_url=None, _f=_openai_factory: _f(
                    api_key, model, params, base_url=base_url
                ),
                "supports_base_url": True,
            }
        elif provider == "azure":
            registry[provider] = {
                "env_key": env_key,
                "default_model": default_model,
                # Azure is instantiated with endpoint metadata in run_voice_bundle_fastapi.
                "factory": lambda api_key, model, params=None, _f=_openai_factory: _f(
                    api_key, normalize_llm_model("azure", model), params
                ),
            }

    return registry


def resolve_voice_llm_base_url(db, organization_id, voice_bundle, llm_provider) -> Optional[str]:
    """Resolve an OpenAI-compatible base URL for custom / gateway-routed LLM legs."""
    provider_key = (
        llm_provider.value if hasattr(llm_provider, "value") else str(llm_provider)
    ).lower()
    if provider_key != "custom":
        return None

    from app.services.credentials import resolve_ai_provider

    ai_provider = resolve_ai_provider(
        provider_key,
        db,
        organization_id,
        credential_id=getattr(voice_bundle, "llm_credential_id", None),
    )
    if not ai_provider:
        return None

    base_url = getattr(ai_provider, "gateway_base_url", None)
    if base_url and str(base_url).strip():
        return str(base_url).strip()
    return None


def instantiate_llm_service(
    provider: str,
    *,
    get_service: Callable[[str], Any],
    api_key: str,
    model: str,
    params: Optional[Any] = None,
    base_url: Optional[str] = None,
):
    """Instantiate a streaming LLM service for the live voice pipeline."""
    registry = get_llm_provider_registry(get_service)
    provider_key = (provider or "").strip().lower()
    cfg = registry.get(provider_key)
    if cfg is None:
        supported = ", ".join(sorted(registry.keys()))
        raise ValueError(
            f"Unsupported LLM provider '{provider_key}'. Supported providers: {supported}"
        )

    factory = cfg["factory"]
    if provider_key == "custom" or cfg.get("supports_base_url"):
        return factory(api_key, model, params, base_url=base_url)
    if base_url:
        logger.debug(
            "Ignoring llm base_url for provider '{}' (not OpenAI-compatible custom routing)",
            provider_key,
        )
    return factory(api_key, model, params)
