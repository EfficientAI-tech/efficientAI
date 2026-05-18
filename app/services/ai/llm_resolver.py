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
from sqlalchemy.orm import Session

from app.models.database import AIProvider
from app.models.enums import ModelProvider


_DEFAULT_MODELS: dict[ModelProvider, str] = {
    ModelProvider.OPENAI: "gpt-5-mini",
    ModelProvider.ANTHROPIC: "claude-sonnet-4-20250514",
    ModelProvider.GOOGLE: "gemini-2.0-flash",
}


def get_llm_provider_and_model(
    organization_id: UUID,
    db: Session,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> Tuple[ModelProvider, str]:
    """Resolve ``(provider_enum, model_str)`` for a one-off LLM call.

    * If both ``provider`` and ``model`` are supplied by the caller we
      validate the provider against the ``ModelProvider`` enum and pass
      both straight through.
    * Otherwise we look at the org's active ``AIProvider`` rows in the
      preference order ``OpenAI -> Anthropic -> Google`` and pair the
      first match with a sensible default model.
    * Raises ``HTTPException(400)`` with an actionable message when no
      AI provider has been configured at all.

    Tests rely on patching ``app.services.ai.llm_resolver.get_llm_provider_and_model``,
    so the public surface here is intentionally minimal.
    """
    if provider and model:
        try:
            provider_enum = ModelProvider(provider.lower())
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported LLM provider: {provider}",
            )
        return provider_enum, model

    for prov in (ModelProvider.OPENAI, ModelProvider.ANTHROPIC, ModelProvider.GOOGLE):
        ai_prov = (
            db.query(AIProvider)
            .filter(
                AIProvider.organization_id == organization_id,
                AIProvider.is_active == True,  # noqa: E712 (SQLAlchemy boolean)
                AIProvider.provider == prov.value,
            )
            .first()
        )
        if ai_prov:
            return prov, model or _DEFAULT_MODELS.get(prov, "gpt-5-mini")

    raise HTTPException(
        status_code=400,
        detail=(
            "No active AI provider configured. Add an OpenAI, Anthropic, "
            "or Google provider in AI Providers settings."
        ),
    )
