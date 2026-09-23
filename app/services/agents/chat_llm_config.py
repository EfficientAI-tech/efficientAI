"""Resolve LLM settings for chat agents (main vs testing user legs)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import Agent, VoiceBundle
from app.models.database import ModelProvider
from app.models.enums import CallMediumEnum


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


def _provider_field_str(raw) -> str:
    if raw is None:
        return ""
    if hasattr(raw, "value"):
        return str(raw.value).strip()
    return str(raw).strip()


def agent_has_chat_simulation_config(agent: Agent) -> bool:
    """True when we can run LLM text simulation (connection layer or legacy bundle)."""
    main_provider = _provider_field_str(getattr(agent, "main_llm_provider", None))
    main_model = (getattr(agent, "main_llm_model", None) or "").strip()
    if main_provider and main_model:
        return True
    medium = (agent.call_medium or CallMediumEnum.PHONE_CALL.value).lower()
    if medium == CallMediumEnum.CHAT.value and agent.voice_bundle_id is not None:
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


def resolve_simulation_llm(
    db: Session,
    *,
    agent: Agent,
    organization_id: UUID,
    leg: Literal["main", "test"],
) -> ResolvedSimulationLlm:
    """Main leg = production agent; test leg = simulated user (falls back to main)."""
    if leg == "test":
        provider_raw = _provider_field_str(agent.test_llm_provider) or _provider_field_str(
            agent.main_llm_provider
        )
        model = (agent.test_llm_model or "").strip() or (agent.main_llm_model or "").strip()
        credential_id = agent.test_llm_credential_id or agent.main_llm_credential_id
        llm_config = (
            agent.test_llm_config
            if isinstance(agent.test_llm_config, dict) and agent.test_llm_config
            else (
                agent.main_llm_config if isinstance(agent.main_llm_config, dict) else None
            )
        )
        source = "test_llm" if (agent.test_llm_provider and agent.test_llm_model) else "main_llm"
    else:
        provider_raw = _provider_field_str(agent.main_llm_provider)
        model = (agent.main_llm_model or "").strip()
        credential_id = agent.main_llm_credential_id
        llm_config = agent.main_llm_config if isinstance(agent.main_llm_config, dict) else None
        source = "main_llm"

    if provider_raw and model:
        return ResolvedSimulationLlm(
            provider=_parse_provider(provider_raw),
            model=model,
            llm_config=llm_config,
            credential_id=credential_id,
            source=source,
        )

    if not agent.voice_bundle_id:
        raise ValueError(
            "Chat agent is missing LLM configuration. Set main LLM on the agent connection layer."
        )

    voice_bundle = (
        db.query(VoiceBundle)
        .filter(
            VoiceBundle.id == agent.voice_bundle_id,
            VoiceBundle.organization_id == organization_id,
        )
        .first()
    )
    if not voice_bundle:
        raise ValueError(f"Voice bundle {agent.voice_bundle_id} not found")

    raw_provider = voice_bundle.llm_provider
    if raw_provider is None:
        raise ValueError("Voice bundle is missing llm_provider")
    vb_model = (voice_bundle.llm_model or "").strip()
    if not vb_model:
        raise ValueError("Voice bundle is missing llm_model")
    return ResolvedSimulationLlm(
        provider=_parse_provider(raw_provider),
        model=vb_model,
        llm_config=voice_bundle.llm_config if isinstance(voice_bundle.llm_config, dict) else None,
        credential_id=getattr(voice_bundle, "llm_credential_id", None),
        source="voice_bundle_legacy",
    )
