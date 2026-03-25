"""
Resolve the LM identifier and API key for GEPA optimization runs.

The LM is derived from the agent's VoiceBundle (or the Evaluator's config as
fallback).  The API key is decrypted from the matching AIProvider row and
passed explicitly on every LiteLLM call -- no environment variables mutated.
"""

from typing import List, Optional

from app.core.encryption import decrypt_api_key
from app.models.database import AIProvider, Evaluator, VoiceBundle


def resolve_lm(
    voice_bundle: Optional[VoiceBundle] = None,
    evaluator: Optional[Evaluator] = None,
) -> str:
    """
    Return a ``"{provider}/{model}"`` string suitable for LiteLLM, resolved
    from the VoiceBundle first, then the Evaluator, with a sensible fallback.
    """
    if voice_bundle and voice_bundle.llm_provider and voice_bundle.llm_model:
        return f"{voice_bundle.llm_provider}/{voice_bundle.llm_model}"
    if evaluator and evaluator.llm_provider and evaluator.llm_model:
        return f"{evaluator.llm_provider}/{evaluator.llm_model}"
    return "openai/gpt-4o"


def resolve_api_key(lm_identifier: str, ai_providers: List[AIProvider]) -> str:
    """
    Given ``"openai/gpt-5.4"`` and the org's provider list, decrypt and
    return the matching API key.
    """
    provider_prefix = lm_identifier.split("/")[0].lower()
    for p in ai_providers:
        if not p.is_active or not p.api_key:
            continue
        if p.provider.lower() == provider_prefix:
            return decrypt_api_key(p.api_key)
    raise RuntimeError(
        f"No active AI provider matching '{provider_prefix}' found. "
        "Add one in Settings > AI Providers."
    )
