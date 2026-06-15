"""
Enumerate judge-capable LLMs available to an organization.

The Judge Alignment surface intentionally does NOT hardcode default judge
models. Instead, it derives the candidate list at runtime from:

    1. The set of `AIProvider` rows the org has configured (from the
       Integrations page).
    2. The text-LLM models those providers expose, as known to
       `app/services/ai/model_config_service.py`.

This keeps the dropdown in the labeling/evaluate UI in lockstep with the
org's actual API key inventory. If the user deletes their OpenAI provider,
gpt-4o-mini disappears from the judge picker automatically.
"""

from typing import Dict, List
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.models.database import AIProvider, ModelProvider
from app.services.ai.model_config_service import model_config_service


# Providers that ship LLM models we can use as a judge. We deliberately
# exclude STT/TTS-only vendors (Deepgram, Cartesia, ElevenLabs, Murf,
# Sarvam, Voicemaker, Smallest) because LiteLLM has no LLM completion
# route for them.
_LLM_CAPABLE_PROVIDERS = {
    ModelProvider.OPENAI.value,
    ModelProvider.ANTHROPIC.value,
    ModelProvider.GOOGLE.value,
    ModelProvider.XAI.value,
    ModelProvider.FIREWORKS.value,
    ModelProvider.COHERE.value,
    ModelProvider.MISTRAL.value,
    ModelProvider.META.value,
    ModelProvider.TOGETHER.value,
    ModelProvider.PERPLEXITY.value,
    ModelProvider.AZURE.value,
    ModelProvider.AWS.value,
    ModelProvider.OPENROUTER.value,
    ModelProvider.CUSTOM.value,
}


def _provider_label(provider_value: str) -> str:
    """Pretty-print provider name for the UI."""
    overrides = {
        "openai": "OpenAI",
        "anthropic": "Anthropic",
        "google": "Google",
        "xai": "xAI",
        "fireworks": "Fireworks AI",
        "cohere": "Cohere",
        "mistral": "Mistral",
        "meta": "Meta",
        "together": "Together",
        "perplexity": "Perplexity",
        "azure": "Azure",
        "aws": "AWS",
        "openrouter": "OpenRouter",
        "custom": "Custom",
    }
    return overrides.get(provider_value.lower(), provider_value.title())


def list_judge_capable_models(
    organization_id: UUID,
    db: Session,
) -> List[Dict[str, str]]:
    """
    Return the judge-capable text-LLM models the org has API keys for.

    Output shape (one entry per provider/model pair)::

        [
            {
                "provider": "openai",
                "provider_label": "OpenAI",
                "model": "gpt-4o-mini",
                "label": "OpenAI / gpt-4o-mini",
            },
            ...
        ]

    Empty list means no LLM-capable AI provider is configured -- the UI
    should surface a CTA pointing the user to the Integrations page.
    """
    providers: List[AIProvider] = (
        db.query(AIProvider)
        .filter(
            AIProvider.organization_id == organization_id,
            AIProvider.is_active == True,  # noqa: E712 - SQLAlchemy comparison
        )
        .all()
    )

    catalog: List[Dict[str, str]] = []
    seen: set = set()

    for ai_provider in providers:
        provider_value = (ai_provider.provider or "").lower()
        if provider_value not in _LLM_CAPABLE_PROVIDERS:
            continue

        try:
            provider_enum = ModelProvider(provider_value)
        except ValueError:
            logger.debug(
                f"[JudgeAlignment] Skipping unknown provider '{provider_value}' "
                f"(org={organization_id})"
            )
            continue

        models: List[str]
        try:
            models = model_config_service.get_models_by_type(provider_enum, "llm")
        except Exception as exc:
            logger.warning(
                f"[JudgeAlignment] Failed to enumerate llm models for "
                f"provider={provider_value}: {exc}"
            )
            models = []

        provider_label = _provider_label(provider_value)
        for model_name in models:
            key = (provider_value, model_name)
            if key in seen:
                continue
            seen.add(key)
            catalog.append(
                {
                    "provider": provider_value,
                    "provider_label": provider_label,
                    "model": model_name,
                    "label": f"{provider_label} / {model_name}",
                }
            )

    catalog.sort(key=lambda m: (m["provider_label"].lower(), m["model"].lower()))
    return catalog
