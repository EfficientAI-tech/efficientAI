"""
Resolve the LM identifier and API key for GEPA optimization runs.

The LM is derived from the agent's VoiceBundle (or the Evaluator's config as
fallback).  The API key is decrypted from the matching AIProvider row and
passed explicitly on every LiteLLM call -- no environment variables mutated.
"""

from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import AIProvider, Evaluator, VoiceBundle
from app.services.ai.llm_gateway import (
    CredentialRoutingContext,
    resolve_effective_routing,
    resolve_litellm_api_key,
    resolve_litellm_model,
    routing_context_from_ai_provider,
)


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


def _find_ai_provider_for_lm(
    lm_identifier: str,
    ai_providers: List[AIProvider],
    *,
    voice_bundle: Optional[VoiceBundle] = None,
) -> Optional[AIProvider]:
    if voice_bundle and voice_bundle.llm_credential_id:
        for provider in ai_providers:
            if provider.id == voice_bundle.llm_credential_id and provider.is_active:
                return provider

    provider_prefix = lm_identifier.split("/")[0].lower()
    fallback: Optional[AIProvider] = None
    for provider in ai_providers:
        if not provider.is_active or not provider.api_key:
            continue
        if provider.provider.lower() != provider_prefix:
            continue
        if provider.is_default:
            return provider
        if fallback is None:
            fallback = provider
    return fallback


def resolve_api_key(
    lm_identifier: str,
    ai_providers: List[AIProvider],
    organization_id: UUID,
    db: Session,
    *,
    voice_bundle: Optional[VoiceBundle] = None,
    credential: Optional[CredentialRoutingContext] = None,
) -> Optional[str]:
    """
    Given ``"openai/gpt-5.4"`` and the org's provider list, decrypt and
    return the matching API key, or None when Bifrost manages provider keys.
    """
    ai_provider = _find_ai_provider_for_lm(
        lm_identifier,
        ai_providers,
        voice_bundle=voice_bundle,
    )
    if not ai_provider:
        raise RuntimeError(
            f"No active AI provider matching '{lm_identifier.split('/')[0].lower()}' found. "
            "Add one in Settings > AI Providers."
        )
    ctx = credential or routing_context_from_ai_provider(ai_provider)
    return resolve_litellm_api_key(
        organization_id,
        db,
        ai_provider,
        credential=ctx,
    )


def resolve_lm_call(
    voice_bundle: Optional[VoiceBundle],
    evaluator: Optional[Evaluator],
    ai_providers: List[AIProvider],
    organization_id: UUID,
    db: Session,
) -> Tuple[str, Optional[str], Optional[CredentialRoutingContext]]:
    """Resolve model string, API key, and credential routing context for GEPA."""
    lm_identifier = resolve_lm(voice_bundle, evaluator)
    ai_provider = _find_ai_provider_for_lm(
        lm_identifier,
        ai_providers,
        voice_bundle=voice_bundle,
    )
    credential_ctx = (
        routing_context_from_ai_provider(ai_provider) if ai_provider else None
    )
    _, effective_routing = resolve_effective_routing(
        organization_id, db, credential_ctx
    )
    model_str = resolve_litellm_model(
        workload_model_str=lm_identifier,
        gateway_active=effective_routing != "direct",
        credential=credential_ctx,
    )
    api_key = (
        resolve_api_key(
            lm_identifier,
            ai_providers,
            organization_id,
            db,
            voice_bundle=voice_bundle,
            credential=credential_ctx,
        )
        if ai_provider
        else None
    )
    return model_str, api_key, credential_ctx
