"""Resolve LLM settings for chat agents (main vs testing user legs)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import Agent
from app.models.database import ModelProvider, VoiceBundle
from app.services.ai.together_models import normalize_together_model_name
from app.models.enums import CallMediumEnum
from app.models.enums import ChatConnectionTypeEnum
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


def _agent_call_medium(agent: Agent) -> str:
    raw = getattr(agent, "call_medium", None) or CallMediumEnum.PHONE_CALL.value
    if hasattr(raw, "value") and not isinstance(raw, str):
        raw = raw.value
    return str(raw).lower()


def _voice_bundle_simulation_llm(
    db: Session,
    *,
    agent: Agent,
) -> Optional[ResolvedSimulationLlm]:
    if _agent_call_medium(agent) == CallMediumEnum.CHAT.value:
        return None
    bundle_id = getattr(agent, "voice_bundle_id", None)
    if not bundle_id:
        return None
    bundle = db.query(VoiceBundle).filter(VoiceBundle.id == bundle_id).first()
    if not bundle:
        return None
    provider_raw = _provider_field_str(bundle.llm_provider)
    model = (bundle.llm_model or "").strip()
    if not provider_raw or not model:
        return None
    prov = _parse_provider(provider_raw)
    return ResolvedSimulationLlm(
        provider=prov,
        model=_normalize_simulation_model(prov, model),
        llm_config=bundle.llm_config if isinstance(bundle.llm_config, dict) else None,
        credential_id=bundle.llm_credential_id,
        source="voice_bundle",
    )


def resolve_simulation_llm(
    db: Session,
    *,
    agent: Agent,
    organization_id: UUID,
    leg: Literal["main", "test"],
) -> ResolvedSimulationLlm:
    """Main leg = production chat agent; test leg = simulated customer.

    Chat agents require explicit agent LLM fields. Voice agents fall back to the voice bundle.
    """
    if leg == "test":
        provider_raw = _provider_field_str(agent.test_llm_provider)
        model = (agent.test_llm_model or "").strip()
        credential_id = agent.test_llm_credential_id
        llm_config = agent.test_llm_config if isinstance(agent.test_llm_config, dict) else None
        source = "test_llm"
    else:
        provider_raw = _provider_field_str(getattr(agent, "main_llm_provider", None))
        model = (getattr(agent, "main_llm_model", None) or "").strip()
        credential_id = getattr(agent, "main_llm_credential_id", None)
        raw_cfg = getattr(agent, "main_llm_config", None)
        llm_config = raw_cfg if isinstance(raw_cfg, dict) else None
        source = "main_llm"

    if not provider_raw or not model:
        if leg == "main":
            conn = normalized_chat_connection_type(agent)
            if conn == ChatConnectionTypeEnum.MESSAGING_CHANNELS.value:
                test_provider = _provider_field_str(agent.test_llm_provider)
                test_model = (getattr(agent, "test_llm_model", None) or "").strip()
                if test_provider and test_model:
                    test_cred = getattr(agent, "test_llm_credential_id", None)
                    test_cfg = getattr(agent, "test_llm_config", None)
                    prov = _parse_provider(test_provider)
                    return ResolvedSimulationLlm(
                        provider=prov,
                        model=_normalize_simulation_model(prov, test_model),
                        llm_config=test_cfg if isinstance(test_cfg, dict) else None,
                        credential_id=test_cred,
                        source="test_llm_for_messaging_production",
                    )
        fallback = _voice_bundle_simulation_llm(db, agent=agent)
        if fallback is not None:
            return fallback
        raise ValueError(_missing_llm_message(leg))

    prov = _parse_provider(provider_raw)
    return ResolvedSimulationLlm(
        provider=prov,
        model=_normalize_simulation_model(prov, model),
        llm_config=llm_config,
        credential_id=credential_id,
        source=source,
    )
