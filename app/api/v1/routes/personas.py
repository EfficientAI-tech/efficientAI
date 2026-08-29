"""
Personas API Routes
CRUD for TTS provider-tied voice personas, voice-options catalog,
and custom voice management (ungated).
"""
from fastapi import APIRouter, Depends, HTTPException, status, Body, Query, UploadFile, File, Form
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from typing import List, Optional, Dict, Any
from uuid import UUID
from pydantic import BaseModel
from loguru import logger

from app.dependencies import get_db, get_organization_id, get_workspace_id, get_api_key, require_enterprise_entitlement
from app.models.database import (
    Persona, Evaluator, EvaluatorResult, TestAgentConversation, CustomTTSVoice,
    PromptOptimizationRun, CallRecording, Agent, AmbientNoiseAsset,
)
from app.models.enums import LanguageEnum, AccentEnum, GenderEnum, BackgroundNoiseEnum, BackgroundNoiseSourceEnum
from app.models.schemas import (
    PersonaCreate, PersonaUpdate, PersonaResponse, PersonaCloneRequest,
    AgentPromptSourcesResponse, GeneratePersonaPromptRequest, GeneratePersonaPromptResponse,
    AmbientNoiseAssetResponse,
    AmbientNoiseAssetUpdateRequest,
)
from app.models.enums import ModelProvider
from app.services.ai.model_config_service import model_config_service
from app.services.ai.llm_resolver import get_llm_provider_and_model as _get_llm_provider_and_model
from app.services.personas.configured_tts_providers import get_configured_tts_provider_keys
from app.services.personas.persona_tts_config import (
    normalize_persona_tts_config,
    validate_persona_tts_config,
)
from app.services.personas.persona_prompt_generation import (
    generate_persona_prompt_from_agent,
    resolve_agent_prompt_sources,
)
from app.services.personas.persona_ambient_noise import (
    ALLOWED_AMBIENT_EXTENSIONS,
    MAX_AMBIENT_UPLOAD_BYTES,
    persona_ambient_s3_key,
    validate_persona_ambient_fields,
)
from app.services.personas.ambient_library import (
    ambient_library_s3_key,
    new_ambient_asset_id,
    sanitize_ambient_name,
    validate_ambient_upload_bytes,
)
from app.services.audio.ambient_catalog import get_ambient_asset_provider, list_ambient_presets, normalize_ambient_preset
from app.services.audio.ambient_mixer import decode_audio_bytes_to_pcm_int16
from app.services.storage.s3_service import s3_service, StorageError
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/personas", tags=["personas"])


def _normalized_persona_tts_config(provider: Optional[str], tts_config: Optional[Dict[str, Any]]):
    return normalize_persona_tts_config(provider, tts_config)


def _ambient_fields_from_create(
    persona: PersonaCreate,
    *,
    db: Session,
    organization_id: UUID,
    workspace_id: UUID,
) -> Dict[str, Any]:
    return validate_persona_ambient_fields(
        source=persona.background_noise_source.value,
        preset=persona.background_noise_preset,
        volume=persona.background_noise_volume,
        s3_key=None,
        asset_id=persona.background_noise_asset_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
        db=db,
        require_custom_file=(
            persona.background_noise_source == BackgroundNoiseSourceEnum.CUSTOM
            and not persona.background_noise_asset_id
        ),
    )


def _apply_ambient_update(
    db_persona: Persona,
    update_data: Dict[str, Any],
    organization_id: UUID,
    workspace_id: UUID,
    db: Session,
) -> Dict[str, Any]:
    if not any(
        key in update_data
        for key in (
            "background_noise_source",
            "background_noise_preset",
            "background_noise_volume",
            "background_noise_asset_id",
        )
    ):
        return update_data

    source = update_data.get(
        "background_noise_source",
        db_persona.background_noise_source or BackgroundNoiseSourceEnum.NONE.value,
    )
    if hasattr(source, "value"):
        source = source.value
    preset = update_data.get("background_noise_preset", db_persona.background_noise_preset)
    volume = update_data.get("background_noise_volume", db_persona.background_noise_volume)
    asset_id = update_data.get("background_noise_asset_id", db_persona.background_noise_asset_id)
    s3_key = db_persona.background_noise_s3_key

    validated = validate_persona_ambient_fields(
        source=source,
        preset=preset,
        volume=volume,
        s3_key=s3_key,
        asset_id=asset_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
        db=db,
        require_custom_file=(
            str(source).lower() == BackgroundNoiseSourceEnum.CUSTOM.value
            and not asset_id
            and not s3_key
        ),
    )
    update_data["background_noise_source"] = validated["background_noise_source"]
    update_data["background_noise_preset"] = validated["background_noise_preset"]
    update_data["background_noise_volume"] = validated["background_noise_volume"]
    update_data["background_noise_asset_id"] = validated["background_noise_asset_id"]
    if validated["background_noise_source"] != BackgroundNoiseSourceEnum.CUSTOM.value:
        update_data["background_noise_s3_key"] = None
        update_data["background_noise_asset_id"] = None
    else:
        update_data["background_noise_s3_key"] = validated["background_noise_s3_key"]
    return update_data


def _get_agent_for_workspace(
    db: Session,
    *,
    agent_id: UUID,
    organization_id: UUID,
    workspace_id: UUID,
) -> Agent:
    agent = db.query(Agent).filter(
        Agent.id == agent_id,
        Agent.organization_id == organization_id,
        Agent.workspace_id == workspace_id,
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    return agent
# ---------------------------------------------------------------------------
# Built-in voice catalog (same data used in voice_playground)
# ---------------------------------------------------------------------------
TTS_VOICES: Dict[str, List[Dict[str, str]]] = {
    "openai": [
        {"id": "alloy", "name": "Alloy", "gender": "Neutral"},
        {"id": "ash", "name": "Ash", "gender": "Male"},
        {"id": "coral", "name": "Coral", "gender": "Female"},
        {"id": "echo", "name": "Echo", "gender": "Male"},
        {"id": "fable", "name": "Fable", "gender": "Male"},
        {"id": "onyx", "name": "Onyx", "gender": "Male"},
        {"id": "nova", "name": "Nova", "gender": "Female"},
        {"id": "sage", "name": "Sage", "gender": "Female"},
        {"id": "shimmer", "name": "Shimmer", "gender": "Female"},
    ],
    "elevenlabs": [
        {"id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel", "gender": "Female"},
        {"id": "AZnzlk1XvdvUeBnXmlld", "name": "Domi", "gender": "Female"},
        {"id": "EXAVITQu4vr4xnSDxMaL", "name": "Bella", "gender": "Female"},
        {"id": "ErXwobaYiN019PkySvjV", "name": "Antoni", "gender": "Male"},
        {"id": "MF3mGyEYCl7XYWbV9V6O", "name": "Elli", "gender": "Female"},
        {"id": "TxGEqnHWrfWFTfGW9XjX", "name": "Josh", "gender": "Male"},
        {"id": "VR6AewLTigWG4xSOukaG", "name": "Arnold", "gender": "Male"},
        {"id": "pNInz6obpgDQGcFmaJgB", "name": "Adam", "gender": "Male"},
        {"id": "yoZ06aMxZJJ28mfd3POQ", "name": "Sam", "gender": "Male"},
        {"id": "jBpfuIE2acCO8z3wKNLl", "name": "Gigi", "gender": "Female"},
    ],
    "cartesia": [
        {"id": "a0e99841-438c-4a64-b679-ae501e7d6091", "name": "Barbershop Man", "gender": "Male"},
        {"id": "79a125e8-cd45-4c13-8a67-188112f4dd22", "name": "British Lady", "gender": "Female"},
        {"id": "b7d50908-b17c-442d-ad8d-7c56a2ec8e67", "name": "Confident Woman", "gender": "Female"},
        {"id": "c8605446-247c-4f39-993c-e0e2ee1c5112", "name": "Friendly Sidekick", "gender": "Male"},
        {"id": "87748186-23bb-4571-ad1f-24094e1acbc5", "name": "Wise Guide", "gender": "Male"},
        {"id": "41534e16-2966-4c6b-9670-111411def906", "name": "Nonfiction Man", "gender": "Male"},
        {"id": "00a77add-48d5-4ef6-8157-71e5437b282d", "name": "Sportsman", "gender": "Male"},
        {"id": "638efaaa-4d0c-442e-b701-3fae16aad012", "name": "Southern Woman", "gender": "Female"},
    ],
    "deepgram": [
        {"id": "aura-asteria-en", "name": "Asteria", "gender": "Female"},
        {"id": "aura-luna-en", "name": "Luna", "gender": "Female"},
        {"id": "aura-stella-en", "name": "Stella", "gender": "Female"},
        {"id": "aura-athena-en", "name": "Athena", "gender": "Female"},
        {"id": "aura-hera-en", "name": "Hera", "gender": "Female"},
        {"id": "aura-orion-en", "name": "Orion", "gender": "Male"},
        {"id": "aura-arcas-en", "name": "Arcas", "gender": "Male"},
        {"id": "aura-perseus-en", "name": "Perseus", "gender": "Male"},
        {"id": "aura-angus-en", "name": "Angus", "gender": "Male"},
        {"id": "aura-orpheus-en", "name": "Orpheus", "gender": "Male"},
        {"id": "aura-helios-en", "name": "Helios", "gender": "Male"},
        {"id": "aura-zeus-en", "name": "Zeus", "gender": "Male"},
    ],
    "google": [
        {"id": "en-US-Neural2-A", "name": "Neural2 A", "gender": "Male"},
        {"id": "en-US-Neural2-C", "name": "Neural2 C", "gender": "Female"},
        {"id": "en-US-Neural2-D", "name": "Neural2 D", "gender": "Male"},
        {"id": "en-US-Neural2-E", "name": "Neural2 E", "gender": "Female"},
        {"id": "en-US-Neural2-F", "name": "Neural2 F", "gender": "Female"},
        {"id": "en-US-Neural2-G", "name": "Neural2 G", "gender": "Female"},
        {"id": "en-US-Neural2-H", "name": "Neural2 H", "gender": "Female"},
        {"id": "en-US-Neural2-I", "name": "Neural2 I", "gender": "Male"},
        {"id": "en-US-Neural2-J", "name": "Neural2 J", "gender": "Male"},
    ],
    "sarvam": [
        {"id": "aditya", "name": "Aditya", "gender": "Male"},
        {"id": "ritu", "name": "Ritu", "gender": "Female"},
        {"id": "ashutosh", "name": "Ashutosh", "gender": "Male"},
        {"id": "priya", "name": "Priya", "gender": "Female"},
        {"id": "neha", "name": "Neha", "gender": "Female"},
        {"id": "rahul", "name": "Rahul", "gender": "Male"},
        {"id": "pooja", "name": "Pooja", "gender": "Female"},
        {"id": "rohan", "name": "Rohan", "gender": "Male"},
        {"id": "simran", "name": "Simran", "gender": "Female"},
        {"id": "kavya", "name": "Kavya", "gender": "Female"},
    ],
    "voicemaker": [
        {"id": "ai3-Jony", "name": "Jony", "gender": "Male"},
        {"id": "ai2-Katie", "name": "Katie", "gender": "Female"},
        {"id": "ai1-Joanna", "name": "Joanna", "gender": "Female"},
        {"id": "pro1-Catherine", "name": "Catherine", "gender": "Female"},
        {"id": "proplus-Richard", "name": "Richard", "gender": "Male"},
        {"id": "proplus-Emma", "name": "Emma", "gender": "Female"},
        {"id": "ai3-Ana", "name": "Ana", "gender": "Female"},
        {"id": "ai3-Lea", "name": "Lea", "gender": "Female"},
        {"id": "ai3-Keiko", "name": "Keiko", "gender": "Female"},
        {"id": "ai3-Liang", "name": "Liang", "gender": "Male"},
    ],
    "smallest": [
        {"id": "daniel", "name": "Daniel", "gender": "Male"},
    ],
    "murf": [],
}

PROVIDER_DISPLAY_NAMES: Dict[str, str] = {
    "openai": "OpenAI",
    "elevenlabs": "ElevenLabs",
    "cartesia": "Cartesia",
    "deepgram": "Deepgram",
    "google": "Google",
    "sarvam": "Sarvam",
    "voicemaker": "VoiceMaker",
    "smallest": "Smallest.ai",
    "murf": "Murf",
    "azure": "Azure",
    "aws": "AWS Polly",
}


# ---------------------------------------------------------------------------
# Custom voice schemas (inline, kept simple)
# ---------------------------------------------------------------------------
class CustomVoiceCreateRequest(BaseModel):
    provider: str
    voice_id: str
    name: str
    gender: Optional[str] = None
    description: Optional[str] = None


class CustomVoiceUpdateRequest(BaseModel):
    voice_id: Optional[str] = None
    name: Optional[str] = None
    gender: Optional[str] = None
    description: Optional[str] = None


def _is_valid_persona_row(persona: Persona) -> bool:
    try:
        # Backward compatibility: legacy persona rows may not have these attrs.
        language_value = str(getattr(persona, "language", "en") or "en").lower()
        accent_value = str(getattr(persona, "accent", "neutral") or "neutral").lower()
        gender_value = str(getattr(persona, "gender", "neutral") or "neutral").lower()
        noise_value = str(getattr(persona, "background_noise", "none") or "none").lower()
        source_value = str(getattr(persona, "background_noise_source", "none") or "none").lower()
        LanguageEnum(language_value)
        AccentEnum(accent_value)
        GenderEnum(gender_value)
        BackgroundNoiseEnum(noise_value)
        BackgroundNoiseSourceEnum(source_value)
        return True
    except Exception:
        return False


@router.post("", response_model=PersonaResponse, status_code=status.HTTP_201_CREATED)
async def create_persona(
    persona: PersonaCreate,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db)
):
    """Create a new persona stamped with the active workspace."""
    try:
        ambient_fields = _ambient_fields_from_create(
            persona,
            db=db,
            organization_id=organization_id,
            workspace_id=workspace_id,
        )
        db_persona = Persona(
            organization_id=organization_id,
            workspace_id=workspace_id,
            name=persona.name,
            gender=persona.gender,
            tts_provider=persona.tts_provider,
            tts_voice_id=persona.tts_voice_id,
            tts_voice_name=persona.tts_voice_name,
            is_custom=persona.is_custom,
            description=persona.description,
            tts_config=_normalized_persona_tts_config(persona.tts_provider, persona.tts_config),
            llm_temperature=persona.llm_temperature,
            llm_max_tokens=persona.llm_max_tokens,
            response_delay_ms=persona.response_delay_ms,
            max_turns=persona.max_turns,
            allow_interruptions=persona.allow_interruptions,
            background_noise_source=ambient_fields["background_noise_source"],
            background_noise_preset=ambient_fields["background_noise_preset"],
            background_noise_volume=ambient_fields["background_noise_volume"],
            background_noise_asset_id=ambient_fields["background_noise_asset_id"],
        )
        db.add(db_persona)
        db.commit()
        db.refresh(db_persona)
        return db_persona
    except IntegrityError as e:
        db.rollback()
        if "foreign key constraint" in str(e.orig).lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid organization_id: {organization_id}"
            )
        elif "unique constraint" in str(e.orig).lower() or "duplicate key" in str(e.orig).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A persona with this name already exists"
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Database constraint violation"
        )
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error creating persona: {str(e)}"
        )


@router.get("", response_model=List[PersonaResponse])
async def list_personas(
    skip: int = 0,
    limit: int = 100,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db)
):
    """List personas for the active workspace."""
    try:
        personas = db.query(Persona).filter(
            Persona.organization_id == organization_id,
            Persona.workspace_id == workspace_id,
        ).offset(skip).limit(limit).all()
        valid_personas: List[Persona] = []
        for persona in personas:
            if _is_valid_persona_row(persona):
                valid_personas.append(persona)
            else:
                logger.warning(
                    "Skipping persona {} with invalid enum values: language={}, accent={}, gender={}, noise={}",
                    persona.id,
                    persona.language,
                    persona.accent,
                    persona.gender,
                    persona.background_noise,
                )
        return valid_personas
    except SQLAlchemyError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error retrieving personas: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error retrieving personas: {str(e)}"
        )


# ============================================
# VOICE OPTIONS (built-in + custom, ungated)
# Must be registered BEFORE /{persona_id} routes.
# ============================================

def _serialize_custom_voice(voice: CustomTTSVoice) -> Dict[str, Any]:
    return {
        "id": str(voice.id),
        "provider": voice.provider,
        "voice_id": voice.voice_id,
        "name": voice.name,
        "gender": voice.gender or "Unknown",
        "description": voice.description,
        "is_custom": True,
        "created_at": voice.created_at.isoformat() if voice.created_at else None,
    }


@router.get("/voice-options", operation_id="getPersonaVoiceOptions")
async def get_voice_options(
    provider: Optional[str] = None,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Return available TTS voices grouped by provider.

    Merges built-in static voices, model-config voices (e.g. Murf voice files),
    and the org's custom voices. Not enterprise-gated.
    """
    model_voices_by_provider: Dict[str, List[Dict[str, Any]]] = {}
    for provider_enum in ModelProvider:
        try:
            tts_models = model_config_service.get_models_by_type(provider_enum, "tts")
        except Exception:
            tts_models = []
        for model_name in tts_models:
            try:
                voices_list = model_config_service.get_voices_for_model(model_name)
            except Exception:
                voices_list = []
            if voices_list and isinstance(voices_list, list):
                existing = model_voices_by_provider.setdefault(provider_enum.value, [])
                for v in voices_list:
                    if isinstance(v, dict) and v.get("id"):
                        existing.append({
                            "id": v["id"],
                            "name": v.get("name", v["id"]),
                            "gender": v.get("gender", "Unknown"),
                        })

    custom_query = db.query(CustomTTSVoice).filter(CustomTTSVoice.organization_id == organization_id)
    if provider:
        custom_query = custom_query.filter(CustomTTSVoice.provider == provider.lower())
    custom_voices = custom_query.order_by(CustomTTSVoice.name.asc()).all()

    custom_by_provider: Dict[str, List[Dict[str, Any]]] = {}
    for cv in custom_voices:
        custom_by_provider.setdefault(cv.provider, []).append({
            "id": cv.voice_id,
            "name": cv.name,
            "gender": cv.gender or "Unknown",
            "is_custom": True,
            "custom_voice_id": str(cv.id),
            "description": cv.description,
        })

    configured_keys = get_configured_tts_provider_keys(organization_id, db)
    all_keys: set = (
        set(TTS_VOICES.keys()) | set(model_voices_by_provider.keys()) | set(custom_by_provider.keys())
    ) & configured_keys
    if provider:
        all_keys = {k for k in all_keys if k == provider.lower()}

    result = []
    for key in sorted(all_keys):
        seen: set = set()
        voices: List[Dict[str, Any]] = []
        for v in TTS_VOICES.get(key, []):
            if v["id"] not in seen:
                seen.add(v["id"])
                voices.append({**v, "is_custom": False})
        for v in model_voices_by_provider.get(key, []):
            if v["id"] not in seen:
                seen.add(v["id"])
                voices.append({**v, "is_custom": False})
        for v in custom_by_provider.get(key, []):
            if v["id"] not in seen:
                seen.add(v["id"])
                voices.append(v)
        if voices:
            result.append({
                "id": key,
                "name": PROVIDER_DISPLAY_NAMES.get(key, key.title()),
                "voices": voices,
            })

    return {"providers": result}


@router.get(
    "/agent-prompt-sources/{agent_id}",
    response_model=AgentPromptSourcesResponse,
    operation_id="getPersonaAgentPromptSources",
)
async def get_agent_prompt_sources(
    agent_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Return agent prompts that can seed a persona description."""
    agent = _get_agent_for_workspace(
        db,
        agent_id=agent_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    sources = resolve_agent_prompt_sources(agent)
    return AgentPromptSourcesResponse(
        agent_id=agent.id,
        agent_name=agent.name,
        test_agent_prompt=sources["test_agent_prompt"],
        agent_prompt=sources["agent_prompt"],
    )


@router.post(
    "/generate-prompt",
    response_model=GeneratePersonaPromptResponse,
    operation_id="generatePersonaPrompt",
)
async def generate_persona_prompt(
    data: GeneratePersonaPromptRequest,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Generate a persona caller prompt from an agent prompt via LLM."""
    agent = _get_agent_for_workspace(
        db,
        agent_id=data.agent_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    provider_enum, model_str = _get_llm_provider_and_model(
        organization_id, db, data.provider, data.model, data.credential_id
    )
    try:
        result = generate_persona_prompt_from_agent(
            agent,
            source=data.source,
            persona_name=data.persona_name,
            persona_gender=data.persona_gender,
            additional_context=data.additional_context,
            llm_provider=provider_enum,
            llm_model=model_str,
            organization_id=organization_id,
            db=db,
            llm_config=data.llm_config,
            credential_id=data.credential_id,
        )
        return GeneratePersonaPromptResponse(
            persona_prompt=result.persona_prompt,
            source_used=result.source_used,
            provider=result.provider,
            model=result.model,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Failed to generate persona prompt for agent {}", data.agent_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate persona prompt: {str(e)}",
        ) from e


# ============================================
# CUSTOM VOICES (ungated, org-scoped)
# Must be registered BEFORE /{persona_id} routes.
# ============================================

@router.get("/custom-voices", operation_id="listPersonaCustomVoices")
async def list_custom_voices(
    provider: Optional[str] = None,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """List custom TTS voices for the organization."""
    query = db.query(CustomTTSVoice).filter(CustomTTSVoice.organization_id == organization_id)
    if provider:
        query = query.filter(CustomTTSVoice.provider == provider.lower())
    voices = query.order_by(CustomTTSVoice.provider.asc(), CustomTTSVoice.name.asc()).all()
    return [_serialize_custom_voice(v) for v in voices]


@router.post("/custom-voices", status_code=status.HTTP_201_CREATED, operation_id="createPersonaCustomVoice")
async def create_custom_voice(
    data: CustomVoiceCreateRequest,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Create a custom TTS voice (org-scoped)."""
    prov = data.provider.strip().lower()
    vid = data.voice_id.strip()
    vname = data.name.strip()
    if not prov or not vid or not vname:
        raise HTTPException(400, "provider, voice_id, and name are required")

    existing = db.query(CustomTTSVoice).filter(
        CustomTTSVoice.organization_id == organization_id,
        CustomTTSVoice.provider == prov,
        CustomTTSVoice.voice_id == vid,
    ).first()
    if existing:
        raise HTTPException(409, f"Custom voice with provider={prov} voice_id={vid} already exists")

    voice = CustomTTSVoice(
        organization_id=organization_id,
        provider=prov,
        voice_id=vid,
        name=vname,
        gender=data.gender,
        description=data.description,
    )
    db.add(voice)
    db.commit()
    db.refresh(voice)
    return _serialize_custom_voice(voice)


@router.put("/custom-voices/{custom_voice_id}", operation_id="updatePersonaCustomVoice")
async def update_custom_voice(
    custom_voice_id: UUID,
    data: CustomVoiceUpdateRequest,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Update a custom TTS voice."""
    voice = db.query(CustomTTSVoice).filter(
        CustomTTSVoice.id == custom_voice_id,
        CustomTTSVoice.organization_id == organization_id,
    ).first()
    if not voice:
        raise HTTPException(404, "Custom voice not found")

    if data.voice_id is not None:
        cleaned = data.voice_id.strip()
        if not cleaned:
            raise HTTPException(400, "voice_id cannot be empty")
        dup = db.query(CustomTTSVoice).filter(
            CustomTTSVoice.organization_id == organization_id,
            CustomTTSVoice.provider == voice.provider,
            CustomTTSVoice.voice_id == cleaned,
            CustomTTSVoice.id != custom_voice_id,
        ).first()
        if dup:
            raise HTTPException(409, f"Another custom voice already uses voice_id={cleaned}")
        voice.voice_id = cleaned
    if data.name is not None:
        voice.name = data.name.strip()
    if data.gender is not None:
        voice.gender = data.gender
    if data.description is not None:
        voice.description = data.description

    db.commit()
    db.refresh(voice)
    return _serialize_custom_voice(voice)


@router.delete("/custom-voices/{custom_voice_id}", operation_id="deletePersonaCustomVoice")
async def delete_custom_voice(
    custom_voice_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Delete a custom TTS voice."""
    voice = db.query(CustomTTSVoice).filter(
        CustomTTSVoice.id == custom_voice_id,
        CustomTTSVoice.organization_id == organization_id,
    ).first()
    if not voice:
        raise HTTPException(404, "Custom voice not found")
    db.delete(voice)
    db.commit()
    return {"message": "Custom voice deleted"}


# ============================================
# AMBIENT NOISE (static paths before /{persona_id})
# ============================================

def _guess_audio_media_type(filename: Optional[str], fallback: str = "audio/wav") -> str:
    if not filename:
        return fallback
    ext = filename.rsplit(".", 1)[-1].lower()
    return {
        "wav": "audio/wav",
        "mp3": "audio/mpeg",
        "ogg": "audio/ogg",
        "m4a": "audio/mp4",
        "flac": "audio/flac",
    }.get(ext, fallback)


@router.get("/ambient-presets", operation_id="listAmbientPresets")
async def list_platform_ambient_presets(
    api_key: str = Depends(get_api_key),
):
    """List platform ambient presets available from installed asset packs."""
    return {"presets": list_ambient_presets()}


@router.get(
    "/ambient-presets/{preset_id}/preview",
    operation_id="previewAmbientPreset",
)
async def preview_ambient_preset(
    preset_id: str,
    api_key: str = Depends(get_api_key),
):
    """Stream a platform preset for in-browser preview."""
    normalized = normalize_ambient_preset(preset_id) or preset_id
    provider = get_ambient_asset_provider()
    try:
        file_bytes = provider.load_wav(normalized)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Preset '{preset_id}' is not available") from exc
    return Response(content=file_bytes, media_type=_guess_audio_media_type(f"{normalized}.wav"))


@router.get(
    "/ambient-library",
    response_model=List[AmbientNoiseAssetResponse],
    operation_id="listAmbientLibrary",
)
async def list_ambient_library(
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
    api_key: str = Depends(get_api_key),
):
    rows = (
        db.query(AmbientNoiseAsset)
        .filter(
            AmbientNoiseAsset.organization_id == organization_id,
            AmbientNoiseAsset.workspace_id == workspace_id,
        )
        .order_by(AmbientNoiseAsset.created_at.desc())
        .all()
    )
    return rows


@router.post(
    "/ambient-library",
    response_model=AmbientNoiseAssetResponse,
    dependencies=[Depends(require_enterprise_entitlement())],
    operation_id="uploadAmbientLibraryAsset",
)
async def upload_ambient_library_asset(
    file: UploadFile = File(...),
    name: Optional[str] = Form(None),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Upload a reusable ambient bed to the workspace library."""
    if not s3_service.is_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=s3_service.get_status_message(),
        )

    filename = file.filename or ""
    file_bytes = await file.read()
    try:
        extension = validate_ambient_upload_bytes(file_bytes, filename=filename)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    asset_id = new_ambient_asset_id()
    display_name = sanitize_ambient_name(name, filename.rsplit(".", 1)[0] if "." in filename else filename)
    s3_key = ambient_library_s3_key(organization_id, asset_id, extension)
    content_type = file.content_type or _guess_audio_media_type(filename)
    try:
        s3_service.upload_file_by_key(file_bytes, s3_key, content_type=content_type)
    except StorageError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    row = AmbientNoiseAsset(
        id=asset_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
        name=display_name,
        s3_key=s3_key,
        original_filename=filename or None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.patch(
    "/ambient-library/{asset_id}",
    response_model=AmbientNoiseAssetResponse,
    dependencies=[Depends(require_enterprise_entitlement())],
    operation_id="updateAmbientLibraryAsset",
)
async def update_ambient_library_asset(
    asset_id: UUID,
    data: AmbientNoiseAssetUpdateRequest,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Rename a library ambient bed."""
    row = db.query(AmbientNoiseAsset).filter(
        AmbientNoiseAsset.id == asset_id,
        AmbientNoiseAsset.organization_id == organization_id,
        AmbientNoiseAsset.workspace_id == workspace_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Ambient library asset not found")

    row.name = sanitize_ambient_name(data.name, row.name)
    db.commit()
    db.refresh(row)
    return row


@router.delete(
    "/ambient-library/{asset_id}",
    dependencies=[Depends(require_enterprise_entitlement())],
    operation_id="deleteAmbientLibraryAsset",
)
async def delete_ambient_library_asset(
    asset_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    row = db.query(AmbientNoiseAsset).filter(
        AmbientNoiseAsset.id == asset_id,
        AmbientNoiseAsset.organization_id == organization_id,
        AmbientNoiseAsset.workspace_id == workspace_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Ambient library asset not found")

    in_use = db.query(Persona).filter(Persona.background_noise_asset_id == asset_id).count()
    if in_use:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ambient bed is used by {in_use} persona(s). Reassign them before deleting.",
        )

    if s3_service.is_enabled():
        try:
            s3_service.delete_file_by_key(row.s3_key)
        except Exception as exc:
            logger.warning("Failed to delete ambient library object {}: {}", row.s3_key, exc)

    db.delete(row)
    db.commit()
    return JSONResponse(status_code=204, content=None)


@router.get(
    "/ambient-library/{asset_id}/preview",
    operation_id="previewAmbientLibraryAsset",
)
async def preview_ambient_library_asset(
    asset_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
    api_key: str = Depends(get_api_key),
):
    """Stream a library ambient bed for in-browser preview."""
    row = db.query(AmbientNoiseAsset).filter(
        AmbientNoiseAsset.id == asset_id,
        AmbientNoiseAsset.organization_id == organization_id,
        AmbientNoiseAsset.workspace_id == workspace_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Ambient library asset not found")
    if not s3_service.is_enabled():
        raise HTTPException(status_code=503, detail=s3_service.get_status_message())
    try:
        file_bytes = s3_service.download_file_by_key(row.s3_key)
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return Response(
        content=file_bytes,
        media_type=_guess_audio_media_type(row.original_filename or row.s3_key),
    )


class AmbientLibraryPreviewUrlResponse(BaseModel):
    url: str
    expires_in: int


@router.get(
    "/ambient-library/{asset_id}/preview-url",
    response_model=AmbientLibraryPreviewUrlResponse,
    operation_id="getAmbientLibraryPreviewUrl",
)
async def get_ambient_library_preview_url(
    asset_id: UUID,
    expiration: int = Query(default=3600, ge=60, le=86400),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
    api_key: str = Depends(get_api_key),
):
    """Return a presigned URL for streaming ambient library preview in the browser."""
    row = db.query(AmbientNoiseAsset).filter(
        AmbientNoiseAsset.id == asset_id,
        AmbientNoiseAsset.organization_id == organization_id,
        AmbientNoiseAsset.workspace_id == workspace_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Ambient library asset not found")
    if not s3_service.is_enabled():
        raise HTTPException(status_code=503, detail=s3_service.get_status_message())
    try:
        url = s3_service.generate_presigned_url_by_key(row.s3_key, expiration=expiration)
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return AmbientLibraryPreviewUrlResponse(url=url, expires_in=expiration)


# ============================================
# PERSONA BY ID (parameterized routes last)
# ============================================

@router.get("/{persona_id}", response_model=PersonaResponse)
async def get_persona(
    persona_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db)
):
    """Get a specific persona within the active workspace."""
    try:
        persona = db.query(Persona).filter(
            Persona.id == persona_id,
            Persona.organization_id == organization_id,
            Persona.workspace_id == workspace_id,
        ).first()
        if not persona:
            raise HTTPException(status_code=404, detail=f"Persona {persona_id} not found")
        if not _is_valid_persona_row(persona):
            raise HTTPException(status_code=404, detail=f"Persona {persona_id} not found")
        return persona
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error retrieving persona: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error retrieving persona: {str(e)}"
        )


@router.put("/{persona_id}", response_model=PersonaResponse)
async def update_persona(
    persona_id: UUID,
    persona_update: PersonaUpdate,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db)
):
    """Update a persona within the active workspace."""
    try:
        db_persona = db.query(Persona).filter(
            Persona.id == persona_id,
            Persona.organization_id == organization_id,
            Persona.workspace_id == workspace_id,
        ).first()
        if not db_persona:
            raise HTTPException(status_code=404, detail=f"Persona {persona_id} not found")
        
        update_data = persona_update.model_dump(exclude_unset=True)
        if db_persona.tts_provider and "tts_provider" in update_data:
            incoming = update_data.get("tts_provider")
            if incoming and str(incoming).strip().lower() != str(db_persona.tts_provider).strip().lower():
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="tts_provider cannot be changed after persona creation. Change the voice instead.",
                )
            update_data.pop("tts_provider", None)
        if "tts_config" in update_data:
            provider = update_data.get("tts_provider", db_persona.tts_provider)
            try:
                validate_persona_tts_config(provider, update_data["tts_config"])
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
            update_data["tts_config"] = _normalized_persona_tts_config(provider, update_data["tts_config"])
        try:
            update_data = _apply_ambient_update(
                db_persona, update_data, organization_id, workspace_id, db
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        for field, value in update_data.items():
            setattr(db_persona, field, value)
        
        db.commit()
        db.refresh(db_persona)
        return db_persona
    except HTTPException:
        raise
    except IntegrityError as e:
        db.rollback()
        if "unique constraint" in str(e.orig).lower() or "duplicate key" in str(e.orig).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A persona with this name already exists"
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Database constraint violation"
        )
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error updating persona: {str(e)}"
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error updating persona: {str(e)}"
        )


@router.delete("/{persona_id}")
async def delete_persona(
    persona_id: UUID,
    force: bool = Query(False, description="Force delete with all dependent records"),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db)
):
    """Delete a persona within the active workspace. Returns 409 if dependent records exist unless force=true."""
    db_persona = db.query(Persona).filter(
        Persona.id == persona_id,
        Persona.organization_id == organization_id,
        Persona.workspace_id == workspace_id,
    ).first()
    if not db_persona:
        raise HTTPException(status_code=404, detail=f"Persona {persona_id} not found")

    evaluators_count = db.query(Evaluator).filter(
        Evaluator.persona_id == persona_id,
        Evaluator.organization_id == organization_id,
    ).count()

    evaluator_results_count = db.query(EvaluatorResult).filter(
        EvaluatorResult.persona_id == persona_id,
        EvaluatorResult.organization_id == organization_id,
    ).count()

    test_conversations_count = db.query(TestAgentConversation).filter(
        TestAgentConversation.persona_id == persona_id,
        TestAgentConversation.organization_id == organization_id,
    ).count()

    dependencies = {}
    if evaluators_count > 0:
        dependencies["evaluators"] = evaluators_count
    if evaluator_results_count > 0:
        dependencies["evaluator_results"] = evaluator_results_count
    if test_conversations_count > 0:
        dependencies["test_conversations"] = test_conversations_count

    if dependencies and not force:
        parts = []
        if evaluators_count > 0:
            parts.append(f"{evaluators_count} evaluator(s)")
        if evaluator_results_count > 0:
            parts.append(f"{evaluator_results_count} evaluator result(s)")
        if test_conversations_count > 0:
            parts.append(f"{test_conversations_count} test conversation(s)")

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": f"Cannot delete persona. It is referenced by: {', '.join(parts)}.",
                "dependencies": dependencies,
                "hint": "Use force=true to delete this persona and all its dependent records.",
            },
        )

    try:
        if dependencies:
            evaluator_ids = [
                e.id for e in db.query(Evaluator.id).filter(
                    Evaluator.persona_id == persona_id,
                    Evaluator.organization_id == organization_id,
                ).all()
            ]

            result_ids = [
                r.id for r in db.query(EvaluatorResult.id).filter(
                    EvaluatorResult.persona_id == persona_id,
                    EvaluatorResult.organization_id == organization_id,
                ).all()
            ]

            # Delete deepest FK children first
            if evaluator_ids:
                db.query(PromptOptimizationRun).filter(
                    PromptOptimizationRun.evaluator_id.in_(evaluator_ids),
                ).delete(synchronize_session=False)

            if result_ids:
                db.query(CallRecording).filter(
                    CallRecording.evaluator_result_id.in_(result_ids),
                ).delete(synchronize_session=False)

            db.query(EvaluatorResult).filter(
                EvaluatorResult.persona_id == persona_id,
                EvaluatorResult.organization_id == organization_id,
            ).delete(synchronize_session=False)

            db.query(Evaluator).filter(
                Evaluator.persona_id == persona_id,
                Evaluator.organization_id == organization_id,
            ).delete(synchronize_session=False)

            db.query(TestAgentConversation).filter(
                TestAgentConversation.persona_id == persona_id,
                TestAgentConversation.organization_id == organization_id,
            ).delete(synchronize_session=False)

        db.delete(db_persona)
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cascade-delete persona dependencies: {str(e.orig)}",
        )

    if dependencies:
        return JSONResponse(
            status_code=200,
            content={
                "message": "Persona and all dependent records deleted successfully.",
                "deleted": dependencies,
            },
        )

    return JSONResponse(status_code=204, content=None)


@router.post("/{persona_id}/clone", response_model=PersonaResponse, status_code=status.HTTP_201_CREATED)
async def clone_persona(
    persona_id: UUID,
    clone_request: PersonaCloneRequest,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db)
):
    """Clone an existing persona within the active workspace."""
    try:
        source_persona = db.query(Persona).filter(
            Persona.id == persona_id,
            Persona.organization_id == organization_id,
            Persona.workspace_id == workspace_id,
        ).first()
        if not source_persona:
            raise HTTPException(status_code=404, detail=f"Persona {persona_id} not found")
        
        new_persona = Persona(
            organization_id=organization_id,
            workspace_id=workspace_id,
            name=clone_request.name if clone_request.name else f"{source_persona.name} (Copy)",
            gender=source_persona.gender,
            tts_provider=source_persona.tts_provider,
            tts_voice_id=source_persona.tts_voice_id,
            tts_voice_name=source_persona.tts_voice_name,
            is_custom=source_persona.is_custom,
            description=source_persona.description,
            tts_config=source_persona.tts_config,
            llm_temperature=source_persona.llm_temperature,
            llm_max_tokens=source_persona.llm_max_tokens,
            response_delay_ms=source_persona.response_delay_ms,
            max_turns=source_persona.max_turns,
            allow_interruptions=source_persona.allow_interruptions,
            background_noise_source=source_persona.background_noise_source,
            background_noise_preset=source_persona.background_noise_preset,
            background_noise_volume=source_persona.background_noise_volume,
            background_noise_s3_key=source_persona.background_noise_s3_key,
            background_noise_asset_id=source_persona.background_noise_asset_id,
        )
        db.add(new_persona)
        db.commit()
        db.refresh(new_persona)
        return new_persona
    except HTTPException:
        raise
    except IntegrityError as e:
        db.rollback()
        if "foreign key constraint" in str(e.orig).lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid organization_id: {organization_id}"
            )
        elif "unique constraint" in str(e.orig).lower() or "duplicate key" in str(e.orig).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A persona with this name already exists"
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Database constraint violation"
        )
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error cloning persona: {str(e)}"
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error cloning persona: {str(e)}"
        )


@router.post(
    "/{persona_id}/ambient-audio",
    response_model=PersonaResponse,
    dependencies=[Depends(require_enterprise_entitlement())],
    operation_id="uploadPersonaAmbientAudio",
)
async def upload_persona_ambient_audio(
    persona_id: UUID,
    file: UploadFile = File(...),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Upload or replace custom ambient audio for a persona (enterprise)."""
    if not s3_service.is_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=s3_service.get_status_message(),
        )

    db_persona = db.query(Persona).filter(
        Persona.id == persona_id,
        Persona.organization_id == organization_id,
        Persona.workspace_id == workspace_id,
    ).first()
    if not db_persona:
        raise HTTPException(status_code=404, detail=f"Persona {persona_id} not found")

    filename = file.filename or ""
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in ALLOWED_AMBIENT_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported ambient audio format. Allowed: {', '.join(sorted(ALLOWED_AMBIENT_EXTENSIONS))}",
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")
    if len(file_bytes) > MAX_AMBIENT_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ambient audio must be at most {MAX_AMBIENT_UPLOAD_BYTES // (1024 * 1024)} MB",
        )

    try:
        decode_audio_bytes_to_pcm_int16(file_bytes, 16000)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not decode ambient audio file: {exc}",
        ) from exc

    s3_key = persona_ambient_s3_key(organization_id, persona_id, extension)
    content_type = file.content_type or f"audio/{extension}"
    try:
        if db_persona.background_noise_s3_key and db_persona.background_noise_s3_key != s3_key:
            try:
                s3_service.delete_file_by_key(db_persona.background_noise_s3_key)
            except Exception:
                logger.warning("Could not delete previous ambient audio key {}", db_persona.background_noise_s3_key)
        s3_service.upload_file_by_key(file_bytes, s3_key, content_type=content_type)
    except StorageError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    db_persona.background_noise_s3_key = s3_key
    db_persona.background_noise_source = BackgroundNoiseSourceEnum.CUSTOM.value
    db.commit()
    db.refresh(db_persona)
    return db_persona


@router.delete(
    "/{persona_id}/ambient-audio",
    response_model=PersonaResponse,
    dependencies=[Depends(require_enterprise_entitlement())],
    operation_id="deletePersonaAmbientAudio",
)
async def delete_persona_ambient_audio(
    persona_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Delete custom ambient audio for a persona (enterprise)."""
    db_persona = db.query(Persona).filter(
        Persona.id == persona_id,
        Persona.organization_id == organization_id,
        Persona.workspace_id == workspace_id,
    ).first()
    if not db_persona:
        raise HTTPException(status_code=404, detail=f"Persona {persona_id} not found")

    if db_persona.background_noise_s3_key and s3_service.is_enabled():
        try:
            s3_service.delete_file_by_key(db_persona.background_noise_s3_key)
        except Exception as exc:
            logger.warning("Failed to delete ambient audio {}: {}", db_persona.background_noise_s3_key, exc)

    db_persona.background_noise_s3_key = None
    if db_persona.background_noise_source == BackgroundNoiseSourceEnum.CUSTOM.value:
        db_persona.background_noise_source = BackgroundNoiseSourceEnum.NONE.value
    db.commit()
    db.refresh(db_persona)
    return db_persona


# ============================================
# SEED DATA (Helper for demo)
# ============================================

@router.post("/seed-data", status_code=status.HTTP_201_CREATED)
async def seed_demo_data(
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db)
):
    """Seed database with example personas and scenarios for the active workspace."""
    from app.models.database import Scenario
    
    try:
        personas_data = [
            {"name": "Grumpy Old Man", "gender": "male", "tts_provider": "openai", "tts_voice_id": "onyx", "tts_voice_name": "Onyx"},
            {"name": "Confused Senior", "gender": "female", "tts_provider": "openai", "tts_voice_id": "nova", "tts_voice_name": "Nova"},
            {"name": "Busy Professional", "gender": "neutral", "tts_provider": "openai", "tts_voice_id": "alloy", "tts_voice_name": "Alloy"},
            {"name": "Friendly Customer", "gender": "female", "tts_provider": "elevenlabs", "tts_voice_id": "21m00Tcm4TlvDq8ikWAM", "tts_voice_name": "Rachel"},
            {"name": "Angry Caller", "gender": "male", "tts_provider": "elevenlabs", "tts_voice_id": "TxGEqnHWrfWFTfGW9XjX", "tts_voice_name": "Josh"},
        ]
        
        # Check if personas already exist to avoid duplicates (within the active workspace)
        existing_persona_names = {p.name for p in db.query(Persona).filter(
            Persona.organization_id == organization_id,
            Persona.workspace_id == workspace_id,
            Persona.name.in_([p["name"] for p in personas_data])
        ).all()}
        
        personas_created = 0
        for persona_data in personas_data:
            if persona_data["name"] not in existing_persona_names:
                persona = Persona(
                    organization_id=organization_id,
                    workspace_id=workspace_id,
                    **persona_data,
                )
                db.add(persona)
                personas_created += 1
        
        # Example scenarios
        scenarios_data = [
            {"name": "Cancel Subscription", "description": "Customer wants to cancel", "required_info": {"account_number": "string", "reason": "string"}},
            {"name": "Check Balance", "description": "Check account balance", "required_info": {"account_number": "string"}},
            {"name": "Technical Support", "description": "Technical issue", "required_info": {"product": "string", "issue": "string"}},
            {"name": "Make Complaint", "description": "File a complaint", "required_info": {"complaint_type": "string"}},
            {"name": "Product Inquiry", "description": "Ask about product", "required_info": {"product_category": "string"}},
        ]
        
        # Check if scenarios already exist to avoid duplicates (within the active workspace)
        existing_scenario_names = {s.name for s in db.query(Scenario).filter(
            Scenario.organization_id == organization_id,
            Scenario.workspace_id == workspace_id,
            Scenario.name.in_([s["name"] for s in scenarios_data])
        ).all()}
        
        scenarios_created = 0
        for scenario_data in scenarios_data:
            if scenario_data["name"] not in existing_scenario_names:
                scenario = Scenario(
                    organization_id=organization_id,
                    workspace_id=workspace_id,
                    **scenario_data,
                )
                db.add(scenario)
                scenarios_created += 1
        
        db.commit()
        
        return {
            "message": "Demo data created",
            "personas_created": personas_created,
            "personas_skipped": len(personas_data) - personas_created,
            "scenarios_created": scenarios_created,
            "scenarios_skipped": len(scenarios_data) - scenarios_created
        }
    except IntegrityError as e:
        db.rollback()
        if "foreign key constraint" in str(e.orig).lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid organization_id: {organization_id}"
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Database constraint violation while seeding data"
        )
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error seeding demo data: {str(e)}"
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error seeding demo data: {str(e)}"
        )


from app.core.auth.capabilities import SIM_MANAGE, SIM_VIEW
from app.core.auth.workspace_route_capabilities import apply_workspace_route_capabilities

apply_workspace_route_capabilities(
    router,
    view_capability=SIM_VIEW,
    manage_capability=SIM_MANAGE,
)

