"""Resolve LLM settings for chat agents (main vs testing user legs)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import Agent
from app.models.database import ModelProvider
from app.services.ai.together_models import normalize_together_model_name
from app.models.enums import CallMediumEnum
from app.services.agents.chat_connection import (
    normalized_chat_connection_type,
    validate_chat_connection_for_agent,
)


@dataclass(frozen=True)
class ResolvedSimulationLlm:
    provider: ModelProvider
    model: str
    llm_config: Optional[dict]
    credential_id: Optional[UUID]
    source: str


def _parse_provider(raw) -> ModelProvider:
    if isinstance(raw, ModelProvider):
        return raw
    return ModelProvider(str(raw).lower())


def _normalize_simulation_model(provider: ModelProvider, model: str) -> str:
    pv = (provider.value if hasattr(provider, "value") else str(provider)).lower()
    if pv in ("together", "meta"):
        return normalize_together_model_name(model)
    return model


def _provider_field_str(raw) -> str:
    if raw is None:
        return ""
    if hasattr(raw, "value"):
        return str(raw.value).strip()
    return str(raw).strip()


def agent_has_chat_simulation_config(agent: Agent) -> bool:
    """True when a chat agent can run text simulation (not used for voice agents)."""
    medium = (agent.call_medium or CallMediumEnum.PHONE_CALL.value).lower()
    if medium != CallMediumEnum.CHAT.value:
        return False

    if validate_chat_connection_for_agent(agent) is None:
        return True
    return False


def should_use_llm_text_simulation(
    agent: Agent,
    *,
    has_voice_bundle: bool,
    has_voice_ai_integration: bool,
) -> bool:
    if agent_has_chat_simulation_config(agent):
        return True
    return has_voice_bundle and not has_voice_ai_integration


def _missing_llm_message(leg: Literal["main", "test"]) -> str:
    if leg == "test":
        return (
            "Chat eval requires a test-agent LLM on the agent "
            "(credential and model under Test agent → Language model)."
        )
    return (
        "Chat agent is missing production LLM configuration. "
        "Set API credential and model on the agent connection."
    )


def resolve_simulation_llm(
    db: Session,
    *,
    agent: Agent,
    organization_id: UUID,
    leg: Literal["main", "test"],
) -> ResolvedSimulationLlm:
    """Main leg = production chat agent; test leg = simulated customer.

    Only uses LLM fields stored on the agent — no org-default or voice-bundle fallback.
    """
    if leg == "test":
        provider_raw = _provider_field_str(agent.test_llm_provider)
        model = (agent.test_llm_model or "").strip()
        credential_id = agent.test_llm_credential_id
        llm_config = agent.test_llm_config if isinstance(agent.test_llm_config, dict) else None
        source = "test_llm"
    else:
        provider_raw = _provider_field_str(agent.main_llm_provider)
        model = (agent.main_llm_model or "").strip()
        credential_id = agent.main_llm_credential_id
        llm_config = agent.main_llm_config if isinstance(agent.main_llm_config, dict) else None
        source = "main_llm"

    if not provider_raw or not model:
        raise ValueError(_missing_llm_message(leg))

    prov = _parse_provider(provider_raw)
    return ResolvedSimulationLlm(
        provider=prov,
        model=_normalize_simulation_model(prov, model),
        llm_config=llm_config,
        credential_id=credential_id,
        source=source,
    )
