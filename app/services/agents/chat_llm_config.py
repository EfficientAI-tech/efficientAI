"""Resolve LLM settings for chat agents (main vs testing user legs)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import Agent, AIProvider, VoiceBundle
from app.models.database import ModelProvider
from app.services.ai.together_models import normalize_together_model_name
from app.services.usage.enabled_models import effective_enabled_models_for_credential
from app.services.voice_agent.llm_voice_providers import default_llm_model
from app.models.enums import CallMediumEnum, ChatConnectionTypeEnum
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
    if agent.voice_bundle_id is not None:
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


def _resolve_voice_bundle_simulation_llm(
    db: Session,
    agent: Agent,
    organization_id: UUID,
    *,
    source: str = "voice_bundle_test_caller",
) -> Optional[ResolvedSimulationLlm]:
    if not agent.voice_bundle_id:
        return None
    voice_bundle = (
        db.query(VoiceBundle)
        .filter(
            VoiceBundle.id == agent.voice_bundle_id,
            VoiceBundle.organization_id == organization_id,
        )
        .first()
    )
    if not voice_bundle:
        return None
    raw_provider = voice_bundle.llm_provider
    if raw_provider is None:
        return None
    vb_model = (voice_bundle.llm_model or "").strip()
    if not vb_model:
        return None
    vb_provider = _parse_provider(raw_provider)
    return ResolvedSimulationLlm(
        provider=vb_provider,
        model=_normalize_simulation_model(vb_provider, vb_model),
        llm_config=voice_bundle.llm_config if isinstance(voice_bundle.llm_config, dict) else None,
        credential_id=getattr(voice_bundle, "llm_credential_id", None),
        source=source,
    )


def _resolve_org_default_simulation_llm(
    db: Session,
    organization_id: UUID,
) -> Optional[ResolvedSimulationLlm]:
    row = (
        db.query(AIProvider)
        .filter(
            AIProvider.organization_id == organization_id,
            AIProvider.is_active.is_(True),
        )
        .order_by(AIProvider.is_default.desc(), AIProvider.updated_at.desc())
        .first()
    )
    if not row:
        return None
    provider_str = _provider_field_str(row.provider)
    if not provider_str:
        return None
    allowlist = effective_enabled_models_for_credential(row)
    gateway_model = (row.gateway_model or "").strip()
    if allowlist:
        model = allowlist[0]
    elif gateway_model:
        model = gateway_model
    else:
        model = default_llm_model(provider_str)
    provider_enum = _parse_provider(provider_str)
    return ResolvedSimulationLlm(
        provider=provider_enum,
        model=_normalize_simulation_model(provider_enum, model),
        llm_config=None,
        credential_id=row.id,
        source="org_default_test_llm",
    )


def resolve_simulation_llm(
    db: Session,
    *,
    agent: Agent,
    organization_id: UUID,
    leg: Literal["main", "test"],
) -> ResolvedSimulationLlm:
    """Main leg = production chat agent; test leg = EfficientAI simulated customer."""
    if leg == "test":
        test_provider = _provider_field_str(agent.test_llm_provider)
        test_model = (agent.test_llm_model or "").strip()
        if test_provider and test_model:
            prov = _parse_provider(test_provider)
            return ResolvedSimulationLlm(
                provider=prov,
                model=_normalize_simulation_model(prov, test_model),
                llm_config=(
                    agent.test_llm_config if isinstance(agent.test_llm_config, dict) else None
                ),
                credential_id=agent.test_llm_credential_id,
                source="test_llm",
            )
        bundle_llm = _resolve_voice_bundle_simulation_llm(db, agent, organization_id)
        if bundle_llm:
            return bundle_llm
        medium = (agent.call_medium or CallMediumEnum.PHONE_CALL.value).lower()
        if medium == CallMediumEnum.CHAT.value:
            org_default = _resolve_org_default_simulation_llm(db, organization_id)
            if org_default:
                return org_default
        provider_raw = ""
        model = ""
        credential_id = None
        llm_config = None
        source = "org_default_test_llm"
    else:
        provider_raw = _provider_field_str(agent.main_llm_provider)
        model = (agent.main_llm_model or "").strip()
        credential_id = agent.main_llm_credential_id
        llm_config = agent.main_llm_config if isinstance(agent.main_llm_config, dict) else None
        source = "main_llm"

    if provider_raw and model:
        prov = _parse_provider(provider_raw)
        return ResolvedSimulationLlm(
            provider=prov,
            model=_normalize_simulation_model(prov, model),
            llm_config=llm_config,
            credential_id=credential_id,
            source=source,
        )

    if leg == "main":
        medium = (agent.call_medium or CallMediumEnum.PHONE_CALL.value).lower()
        conn = normalized_chat_connection_type(agent)
        if medium == CallMediumEnum.CHAT.value and conn in (
            ChatConnectionTypeEnum.INTERNAL_LLM.value,
            ChatConnectionTypeEnum.MESSAGING_CHANNELS.value,
        ):
            org_default = _resolve_org_default_simulation_llm(db, organization_id)
            if org_default:
                source = (
                    "org_default_production_sim"
                    if conn != ChatConnectionTypeEnum.INTERNAL_LLM.value
                    else "org_default_main_sim"
                )
                return ResolvedSimulationLlm(
                    provider=org_default.provider,
                    model=org_default.model,
                    llm_config=org_default.llm_config,
                    credential_id=org_default.credential_id,
                    source=source,
                )

    bundle_llm = _resolve_voice_bundle_simulation_llm(
        db, agent, organization_id, source="voice_bundle_legacy"
    )
    if bundle_llm:
        return bundle_llm

    medium = (agent.call_medium or CallMediumEnum.PHONE_CALL.value).lower()
    if medium == CallMediumEnum.CHAT.value:
        raise ValueError(
            "Chat simulation requires a test voice bundle (Test Agent → voice stack) "
            "or an organization AI provider under Settings → AI Providers."
        )
    raise ValueError(
        "Chat agent is missing LLM configuration. Set main LLM on the agent connection layer."
    )
