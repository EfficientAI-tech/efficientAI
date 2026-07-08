"""Resolve agent configuration for Vobiz telephony Pipecat pipelines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.encryption import decrypt_api_key
from app.models.database import (
    AIProvider,
    Agent,
    Integration,
    IntegrationPlatform,
    ModelProvider,
    Persona,
    Scenario,
    VoiceBundle,
    Workspace,
)


@dataclass
class VobizAgentContext:
    agent: Agent
    organization_id: UUID
    workspace_id: Optional[UUID]
    voice_bundle: Optional[VoiceBundle]
    use_voice_bundle_pipeline: bool
    system_instruction: Optional[str]
    google_api_key: Optional[str]
    model_name: Optional[str]
    stt_api_key: Optional[str]
    tts_api_key: Optional[str]
    llm_api_key: Optional[str]


def _resolve_api_key_for_provider(db: Session, organization_id: UUID, provider: ModelProvider) -> Optional[str]:
    provider_value = provider.value if hasattr(provider, "value") else provider

    ai_provider_rec = db.query(AIProvider).filter(
        AIProvider.organization_id == organization_id,
        AIProvider.provider == provider_value,
        AIProvider.is_active.is_(True),
    ).first()
    if not ai_provider_rec:
        ai_provider_rec = db.query(AIProvider).filter(
            AIProvider.organization_id == organization_id,
            func.lower(AIProvider.provider) == provider_value.lower(),
            AIProvider.is_active.is_(True),
        ).first()
    if ai_provider_rec:
        return decrypt_api_key(ai_provider_rec.api_key)

    platform_map = {
        ModelProvider.DEEPGRAM: IntegrationPlatform.DEEPGRAM,
        ModelProvider.CARTESIA: IntegrationPlatform.CARTESIA,
        ModelProvider.ELEVENLABS: IntegrationPlatform.ELEVENLABS,
        ModelProvider.MURF: IntegrationPlatform.MURF,
        ModelProvider.SARVAM: IntegrationPlatform.SARVAM,
        ModelProvider.VOICEMAKER: IntegrationPlatform.VOICEMAKER,
        ModelProvider.SMALLEST: IntegrationPlatform.SMALLEST,
    }
    plat = platform_map.get(provider)
    if plat:
        plat_value = plat.value if hasattr(plat, "value") else plat
        integ = db.query(Integration).filter(
            Integration.organization_id == organization_id,
            Integration.platform == plat_value,
            Integration.is_active.is_(True),
        ).first()
        if not integ:
            integ = db.query(Integration).filter(
                Integration.organization_id == organization_id,
                func.lower(Integration.platform) == plat_value.lower(),
                Integration.is_active.is_(True),
            ).first()
        if integ:
            return decrypt_api_key(integ.api_key)
    return None


def build_system_instruction(
    db: Session,
    *,
    agent: Agent,
    organization_id: UUID,
    workspace_id: Optional[UUID],
    persona_id: Optional[str] = None,
    scenario_id: Optional[str] = None,
) -> Optional[str]:
    instruction_parts = []
    if agent.description:
        instruction_parts.append(agent.description)

    if persona_id:
        try:
            persona_uuid = UUID(persona_id)
            persona_query = db.query(Persona).filter(
                Persona.id == persona_uuid,
                Persona.organization_id == organization_id,
            )
            if workspace_id is not None:
                persona_query = persona_query.filter(Persona.workspace_id == workspace_id)
            persona = persona_query.first()
            if persona:
                persona_parts = [f"\n\nPersona: {persona.name}"]
                if persona.gender:
                    gender_val = persona.gender.value if hasattr(persona.gender, "value") else persona.gender
                    persona_parts.append(f"Gender: {gender_val}")
                if getattr(persona, "tts_provider", None):
                    persona_parts.append(f"Voice provider: {persona.tts_provider}")
                if getattr(persona, "tts_voice_name", None):
                    persona_parts.append(f"Voice: {persona.tts_voice_name}")
                instruction_parts.append("\n".join(persona_parts))
        except ValueError:
            pass

    if scenario_id:
        try:
            scenario_uuid = UUID(scenario_id)
            scenario_query = db.query(Scenario).filter(
                Scenario.id == scenario_uuid,
                Scenario.organization_id == organization_id,
            )
            if workspace_id is not None:
                scenario_query = scenario_query.filter(Scenario.workspace_id == workspace_id)
            scenario = scenario_query.first()
            if scenario:
                scenario_parts = [f"\n\nScenario: {scenario.name}"]
                if scenario.description:
                    scenario_parts.append(f"Description: {scenario.description}")
                if scenario.required_info:
                    required_info_str = (
                        ", ".join([f"{k}: {v}" for k, v in scenario.required_info.items()])
                        if isinstance(scenario.required_info, dict)
                        else str(scenario.required_info)
                    )
                    if required_info_str:
                        scenario_parts.append(f"Required information to collect: {required_info_str}")
                instruction_parts.append("\n".join(scenario_parts))
        except ValueError:
            pass

    return "\n".join(instruction_parts) if instruction_parts else None


def resolve_vobiz_agent_context(
    db: Session,
    *,
    agent_id: UUID,
    organization_id: UUID,
    persona_id: Optional[str] = None,
    scenario_id: Optional[str] = None,
) -> VobizAgentContext:
    agent = db.query(Agent).filter(
        Agent.id == agent_id,
        Agent.organization_id == organization_id,
    ).first()
    if not agent:
        raise ValueError("Agent not found for organization")

    workspace_id: Optional[UUID] = agent.workspace_id
    if workspace_id is None:
        default_ws = db.query(Workspace).filter(
            Workspace.organization_id == organization_id,
            Workspace.is_default.is_(True),
        ).first()
        if default_ws:
            workspace_id = default_ws.id

    voice_bundle = None
    if agent.voice_bundle_id:
        voice_bundle = db.query(VoiceBundle).filter(
            VoiceBundle.id == agent.voice_bundle_id,
            VoiceBundle.organization_id == organization_id,
        ).first()

    use_voice_bundle_pipeline = bool(voice_bundle and voice_bundle.bundle_type == "stt_llm_tts")
    system_instruction = build_system_instruction(
        db,
        agent=agent,
        organization_id=organization_id,
        workspace_id=workspace_id,
        persona_id=persona_id,
        scenario_id=scenario_id,
    )

    google_api_key = None
    model_name = None
    stt_api_key = None
    tts_api_key = None
    llm_api_key = None

    if use_voice_bundle_pipeline and voice_bundle:
        if voice_bundle.stt_provider:
            stt_api_key = _resolve_api_key_for_provider(db, organization_id, voice_bundle.stt_provider)
        if voice_bundle.tts_provider:
            tts_api_key = _resolve_api_key_for_provider(db, organization_id, voice_bundle.tts_provider)
        if voice_bundle.llm_provider:
            llm_api_key = _resolve_api_key_for_provider(db, organization_id, voice_bundle.llm_provider)
    else:
        ai_provider = None
        if agent.ai_provider_id:
            ai_provider = db.query(AIProvider).filter(
                AIProvider.id == agent.ai_provider_id,
                AIProvider.organization_id == organization_id,
                AIProvider.is_active.is_(True),
            ).first()
        if not ai_provider:
            google_value = ModelProvider.GOOGLE.value
            ai_provider = db.query(AIProvider).filter(
                AIProvider.organization_id == organization_id,
                AIProvider.provider == google_value,
                AIProvider.is_active.is_(True),
            ).first()
            if not ai_provider:
                ai_provider = db.query(AIProvider).filter(
                    AIProvider.organization_id == organization_id,
                    func.lower(AIProvider.provider) == google_value.lower(),
                    AIProvider.is_active.is_(True),
                ).first()
        if not ai_provider:
            raise ValueError(
                "AI Provider not configured. Configure a Google AI Provider or assign a voice bundle."
            )
        google_api_key = decrypt_api_key(ai_provider.api_key)
        if voice_bundle and voice_bundle.bundle_type == "s2s" and voice_bundle.s2s_model:
            model_name = voice_bundle.s2s_model

    return VobizAgentContext(
        agent=agent,
        organization_id=organization_id,
        workspace_id=workspace_id,
        voice_bundle=voice_bundle,
        use_voice_bundle_pipeline=use_voice_bundle_pipeline,
        system_instruction=system_instruction,
        google_api_key=google_api_key,
        model_name=model_name,
        stt_api_key=stt_api_key,
        tts_api_key=tts_api_key,
        llm_api_key=llm_api_key,
    )


def vobiz_webhook_base_url() -> str:
    from app.config import settings

    base = settings.VOBIZ_WEBHOOK_BASE_URL or settings.PLIVO_WEBHOOK_BASE_URL
    if not base:
        raise ValueError("VOBIZ_WEBHOOK_BASE_URL is not configured")
    return base.rstrip("/")


def build_vobiz_ws_url(
    *,
    agent_id: str,
    session: str,
    persona_id: Optional[str] = None,
    scenario_id: Optional[str] = None,
) -> str:
    from app.config import settings
    from app.services.media_urls import media_ws_base_url
    from urllib.parse import quote

    ws_base = media_ws_base_url()
    if not ws_base:
        base = vobiz_webhook_base_url()
        ws_base = base.replace("https://", "wss://").replace("http://", "ws://")
    query = f"agent_id={quote(agent_id)}&session={quote(session)}"
    if persona_id:
        query += f"&persona_id={quote(persona_id)}"
    if scenario_id:
        query += f"&scenario_id={quote(scenario_id)}"
    return f"{ws_base}{settings.API_V1_PREFIX}/telephony/vobiz/ws?{query}"


def extract_webhook_params(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize Vobiz/Plivo-style webhook parameters."""
    return {
        "to": (
            payload.get("To")
            or payload.get("to")
            or payload.get("Destination")
            or payload.get("destination")
            or payload.get("Called")
            or payload.get("called")
        ),
        "from": (
            payload.get("From")
            or payload.get("from")
            or payload.get("Caller")
            or payload.get("caller")
            or payload.get("Source")
            or payload.get("source")
        ),
        "call_uuid": (
            payload.get("CallUUID")
            or payload.get("CallSid")
            or payload.get("call_sid")
            or payload.get("Sid")
            or payload.get("CallId")
        ),
        "call_status": payload.get("CallStatus") or payload.get("Event") or payload.get("Status"),
        "recording_url": (
            payload.get("RecordUrl")
            or payload.get("RecordingUrl")
            or payload.get("recording_url")
            or payload.get("RecordFile")
            or payload.get("record_file")
        ),
        "recording_id": payload.get("RecordingID") or payload.get("recording_id"),
    }
