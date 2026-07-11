"""Shared resolver for picking an LLM (provider + model) at request time.

The original copy lives at the top of ``app/api/v1/routes/prompt_partials.py``.
A second consumer was added for the call-import evaluation insights
endpoint, so the helper now lives here and both routes import from this
module to keep the "auto-detect first available provider" + "fallback
to a sensible default model" behavior identical across surfaces.
"""

from typing import Optional, Tuple
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models.database import AIProvider
from app.models.enums import ModelProvider
from app.services.ai.llm_gateway import (
    resolve_effective_routing,
    routing_context_from_ai_provider,
)
from app.services.credentials import resolve_ai_provider


_DEFAULT_MODELS: dict[ModelProvider, str] = {
    ModelProvider.OPENAI: "gpt-5-mini",
    ModelProvider.ANTHROPIC: "claude-sonnet-4-20250514",
    ModelProvider.GOOGLE: "gemini-2.0-flash",
}

_AUTO_DETECT_PRIORITY = (
    ModelProvider.OPENAI,
    ModelProvider.ANTHROPIC,
    ModelProvider.GOOGLE,
)


def _provider_enum(provider: str) -> ModelProvider:
    try:
        return ModelProvider(provider.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported LLM provider: {provider}",
        )


def _default_model_for(provider: ModelProvider) -> str:
    return _DEFAULT_MODELS.get(provider, "gpt-5-mini")


def _resolved_model_for_row(
    organization_id: UUID,
    db: Session,
    ai_prov: AIProvider,
    explicit_model: Optional[str],
) -> str:
    if explicit_model:
        return explicit_model
    ctx = routing_context_from_ai_provider(ai_prov)
    _, effective = resolve_effective_routing(organization_id, db, ctx)
    if effective != "direct" and ctx.gateway_model:
        return ctx.gateway_model
    try:
        return _default_model_for(ModelProvider(ai_prov.provider.lower()))
    except ValueError:
        return "gpt-5-mini"


def get_llm_provider_and_model(
    organization_id: UUID,
    db: Session,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    credential_id: Optional[UUID] = None,
) -> Tuple[ModelProvider, str]:
    """Resolve ``(provider_enum, model_str)`` for a one-off LLM call.

    * When ``credential_id`` is supplied we resolve that exact active
      ``AIProvider`` row (required when multiple credentials share a
      provider, e.g. several ``custom`` gateway models).
    * When ``provider`` is supplied we resolve the matching active
      ``AIProvider`` row. An omitted ``model`` uses the credential's
      ``gateway_model`` when gateway routing is active, otherwise a
      provider-specific default.
    * When both are omitted we prefer the org-wide default credential,
      then OpenAI -> Anthropic -> Google, then any other active row.
    * Raises ``HTTPException(400)`` with an actionable message when no
      AI provider has been configured.

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
        if not ai_prov:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"No active AI provider found for credential {credential_id}. "
                    "Check AI Providers settings."
                ),
            )
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

    if explicit_provider:
        provider_enum = _provider_enum(explicit_provider)
        ai_prov = resolve_ai_provider(provider_enum.value, db, organization_id)
        if not ai_prov:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"No active AI provider configured for {explicit_provider}. "
                    "Add one in AI Providers settings."
                ),
            )
        model_str = _resolved_model_for_row(
            organization_id, db, ai_prov, explicit_model
        )
        return provider_enum, model_str

    default_row = (
        db.query(AIProvider)
        .filter(
            AIProvider.organization_id == organization_id,
            AIProvider.is_active == True,  # noqa: E712 (SQLAlchemy boolean)
            AIProvider.is_default == True,  # noqa: E712
        )
        .order_by(desc(AIProvider.updated_at))
        .first()
    )
    if default_row:
        provider_enum = _provider_enum(default_row.provider)
        model_str = _resolved_model_for_row(
            organization_id, db, default_row, explicit_model
        )
        return provider_enum, model_str

    for prov in _AUTO_DETECT_PRIORITY:
        ai_prov = resolve_ai_provider(prov.value, db, organization_id)
        if ai_prov:
            model_str = _resolved_model_for_row(
                organization_id, db, ai_prov, explicit_model
            )
            return prov, model_str

    fallback = (
        db.query(AIProvider)
        .filter(
            AIProvider.organization_id == organization_id,
            AIProvider.is_active == True,  # noqa: E712
        )
        .order_by(desc(AIProvider.updated_at))
        .first()
    )
    if fallback:
        provider_enum = _provider_enum(fallback.provider)
        model_str = _resolved_model_for_row(
            organization_id, db, fallback, explicit_model
        )
        return provider_enum, model_str

    raise HTTPException(
        status_code=400,
        detail=(
            "No active AI provider configured. Add an AI provider "
            "in AI Providers settings."
        ),
    )
