"""Shared resolver for picking an LLM (provider + model) at request time.

The original copy lives at the top of ``app/api/v1/routes/prompt_partials.py``.
A second consumer was added for the call-import evaluation insights
endpoint, so the helper now lives here. Callers must pass an explicit
provider and/or credential_id and model (unless gateway_model pins the model).
"""

from typing import Optional, Tuple
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models.database import AIProvider, Integration
from app.models.enums import IntegrationPlatform, ModelProvider
from app.services.ai.llm_gateway import (
    resolve_effective_routing,
    routing_context_from_ai_provider,
)
from app.services.credentials import resolve_ai_provider, resolve_integration
from app.services.ai.model_config_service import model_config_service
from app.services.usage.enabled_models import (
    effective_enabled_models_for_credential,
    filter_models_by_credential,
)
from app.services.ai.together_models import (
    TOGETHER_SERVERLESS_DEFAULT_MODEL,
    normalize_together_model_name,
)
from app.services.voice_agent.llm_voice_providers import (
    LLM_VOICE_PROVIDER_KEYS,
    default_llm_model,
)


_DEFAULT_MODELS: dict[ModelProvider, str] = {
    ModelProvider.OPENAI: "gpt-5-mini",
    ModelProvider.ANTHROPIC: "claude-sonnet-4.6",
    ModelProvider.GOOGLE: "gemini-2.5-flash",
    ModelProvider.SARVAM: "sarvam-30b",
    ModelProvider.FIREWORKS: "gpt-oss-20b",
    ModelProvider.TOGETHER: TOGETHER_SERVERLESS_DEFAULT_MODEL,
    ModelProvider.META: TOGETHER_SERVERLESS_DEFAULT_MODEL,
    ModelProvider.OPENROUTER: "openai/gpt-4o-2024-11-20",
    ModelProvider.XAI: "grok-3-beta",
}

_AUTO_DETECT_PRIORITY = (
    ModelProvider.OPENAI,
    ModelProvider.ANTHROPIC,
    ModelProvider.GOOGLE,
)

# Voice-platform integrations that also expose LLM models (credentials live
# in the Integration table rather than AIProvider).
_INTEGRATION_LLM_PLATFORMS = {
    IntegrationPlatform.SARVAM.value: ModelProvider.SARVAM,
}


def _provider_enum(provider: str) -> ModelProvider:
    try:
        return ModelProvider(provider.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported LLM provider: {provider}",
        )


def _default_model_for(
    provider: ModelProvider,
    ai_prov: Optional[AIProvider] = None,
) -> str:
    if ai_prov is not None:
        allowlist = effective_enabled_models_for_credential(ai_prov)
        if allowlist:
            return _maybe_normalize_together_model(provider, allowlist[0])

    preset = _DEFAULT_MODELS.get(provider)
    if preset:
        return preset

    catalog = model_config_service.get_models_by_type(provider, "llm")
    if ai_prov is not None:
        catalog = filter_models_by_credential(ai_prov, catalog)
    if catalog:
        return catalog[0]

    if provider.value in LLM_VOICE_PROVIDER_KEYS:
        return default_llm_model(provider.value)

    if provider == ModelProvider.OPENAI:
        return "gpt-5-mini"

    raise HTTPException(
        status_code=400,
        detail=(
            f"No default LLM model available for {provider.value}. "
            "Select a model explicitly or configure one in AI Providers."
        ),
    )


def _provider_enum_from_integration_platform(platform: str) -> Optional[ModelProvider]:
    return _INTEGRATION_LLM_PLATFORMS.get((platform or "").lower())


def _maybe_normalize_together_model(provider: ModelProvider, model: str) -> str:
    if provider in (ModelProvider.TOGETHER, ModelProvider.META):
        return normalize_together_model_name(model)
    return model


def _resolved_model_for_row(
    organization_id: UUID,
    db: Session,
    ai_prov: AIProvider,
    explicit_model: Optional[str],
) -> str:
    provider_enum = _provider_enum(ai_prov.provider)
    if explicit_model:
        return _maybe_normalize_together_model(provider_enum, explicit_model)
    ctx = routing_context_from_ai_provider(ai_prov)
    _, effective = resolve_effective_routing(organization_id, db, ctx)
    if effective != "direct" and ctx.gateway_model:
        return _maybe_normalize_together_model(provider_enum, ctx.gateway_model)
    raise HTTPException(
        status_code=400,
        detail=(
            "LLM model is required. Select a model from the enabled list for this credential, "
            "or use a gateway credential with a pinned gateway model."
        ),
    )


def _resolved_model_for_integration(
    provider_enum: ModelProvider,
    explicit_model: Optional[str],
) -> str:
    if explicit_model:
        return explicit_model
    raise HTTPException(
        status_code=400,
        detail=(
            f"LLM model is required for {provider_enum.value}. "
            "Select a model explicitly in the UI."
        ),
    )


def _resolve_integration_llm_provider(
    organization_id: UUID,
    db: Session,
    *,
    platform: Optional[str] = None,
    credential_id: Optional[UUID] = None,
) -> Optional[Tuple[ModelProvider, Integration]]:
    """Return (provider_enum, integration_row) when an LLM-capable integration exists."""
    if credential_id is not None:
        integration = (
            db.query(Integration)
            .filter(
                Integration.id == credential_id,
                Integration.organization_id == organization_id,
                Integration.is_active == True,  # noqa: E712
            )
            .first()
        )
        if integration is None:
            return None
        provider_enum = _provider_enum_from_integration_platform(integration.platform)
        if provider_enum is None:
            return None
        return provider_enum, integration

    if not platform:
        return None
    provider_enum = _provider_enum_from_integration_platform(platform)
    if provider_enum is None:
        return None
    integration = resolve_integration(platform, db, organization_id)
    if integration is None:
        return None
    return provider_enum, integration


def get_llm_provider_and_model(
    organization_id: UUID,
    db: Session,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    credential_id: Optional[UUID] = None,
) -> Tuple[ModelProvider, str]:
    """Resolve ``(provider_enum, model_str)`` for a one-off LLM call.

    * When ``credential_id`` is supplied we resolve that exact active
      ``AIProvider`` row, or an ``Integration`` row for voice-platform
      LLM providers such as Sarvam.
    * When ``provider`` is supplied we resolve the matching active
      ``AIProvider`` row, falling back to Integration when configured.
    * When both provider and credential_id are omitted, returns 400 — callers
      must pass an explicit provider and/or credential_id (and model when
      not pinned by gateway_model).
    * Raises ``HTTPException(400)`` with an actionable message when no
      LLM credential has been configured.

    Tests rely on patching ``app.services.ai.llm_resolver.get_llm_provider_and_model``,
    so the public surface here is intentionally minimal.
    """
    explicit_model = (model or "").strip() or None
    explicit_provider = (provider or "").strip() or None

    if credential_id is not None:
        ai_prov = (
            db.query(AIProvider)
            .filter(
                AIProvider.id == credential_id,
                AIProvider.organization_id == organization_id,
                AIProvider.is_active == True,  # noqa: E712
            )
            .first()
        )
        if ai_prov:
            provider_enum = _provider_enum(ai_prov.provider)
            if (
                explicit_provider
                and explicit_provider.lower() != ai_prov.provider.lower()
            ):
                raise HTTPException(
                    status_code=400,
                    detail="provider does not match the selected credential.",
                )
            model_str = _resolved_model_for_row(
                organization_id, db, ai_prov, explicit_model
            )
            return provider_enum, model_str

        integration_match = _resolve_integration_llm_provider(
            organization_id,
            db,
            credential_id=credential_id,
        )
        if integration_match:
            provider_enum, integration = integration_match
            if (
                explicit_provider
                and explicit_provider.lower() != integration.platform.lower()
            ):
                raise HTTPException(
                    status_code=400,
                    detail="provider does not match the selected credential.",
                )
            return provider_enum, _resolved_model_for_integration(
                provider_enum, explicit_model
            )

        raise HTTPException(
            status_code=400,
            detail=(
                f"No active LLM credential found for credential {credential_id}. "
                "Check AI Providers or Integrations settings."
            ),
        )

    if explicit_provider:
        provider_enum = _provider_enum(explicit_provider)
        ai_prov = resolve_ai_provider(provider_enum.value, db, organization_id)
        if ai_prov:
            model_str = _resolved_model_for_row(
                organization_id, db, ai_prov, explicit_model
            )
            return provider_enum, model_str

        integration_match = _resolve_integration_llm_provider(
            organization_id,
            db,
            platform=explicit_provider,
        )
        if integration_match:
            matched_enum, _integration = integration_match
            return matched_enum, _resolved_model_for_integration(
                matched_enum, explicit_model
            )

        raise HTTPException(
            status_code=400,
            detail=(
                f"No active credential configured for {explicit_provider}. "
                "Add one in AI Providers or Integrations settings."
            ),
        )

    raise HTTPException(
        status_code=400,
        detail=(
            "LLM provider and model are required. Select a credential and model "
            "in the UI (or pass provider, model, and optional credential_id)."
        ),
    )
