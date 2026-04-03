"""
Personas API Routes
CRUD for TTS provider-tied voice personas, voice-options catalog,
and custom voice management (ungated).
"""
from fastapi import APIRouter, Depends, HTTPException, status, Body, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from typing import List, Optional, Dict, Any
from uuid import UUID
from pydantic import BaseModel

from app.dependencies import get_db, get_organization_id
from app.models.database import (
    Persona, Evaluator, EvaluatorResult, TestAgentConversation, CustomTTSVoice,
    PromptOptimizationRun, CallRecording,
)
from app.models.schemas import (
    PersonaCreate, PersonaUpdate, PersonaResponse, PersonaCloneRequest
)
from app.models.enums import ModelProvider
from app.services.ai.model_config_service import model_config_service

router = APIRouter(prefix="/personas", tags=["personas"])


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


@router.post("", response_model=PersonaResponse, status_code=status.HTTP_201_CREATED)
async def create_persona(
    persona: PersonaCreate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Create a new persona"""
    try:
        db_persona = Persona(
            organization_id=organization_id,
            name=persona.name,
            gender=persona.gender,
            tts_provider=persona.tts_provider,
            tts_voice_id=persona.tts_voice_id,
            tts_voice_name=persona.tts_voice_name,
            is_custom=persona.is_custom,
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
    db: Session = Depends(get_db)
):
    """Get list of all personas for the organization"""
    try:
        personas = db.query(Persona).filter(
            Persona.organization_id == organization_id
        ).offset(skip).limit(limit).all()
        return personas
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

    all_keys: set = set(TTS_VOICES.keys()) | set(model_voices_by_provider.keys()) | set(custom_by_provider.keys())
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
# PERSONA BY ID (parameterized routes last)
# ============================================

@router.get("/{persona_id}", response_model=PersonaResponse)
async def get_persona(
    persona_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Get a specific persona by ID"""
    try:
        persona = db.query(Persona).filter(
            Persona.id == persona_id,
            Persona.organization_id == organization_id
        ).first()
        if not persona:
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
    db: Session = Depends(get_db)
):
    """Update an existing persona"""
    try:
        db_persona = db.query(Persona).filter(
            Persona.id == persona_id,
            Persona.organization_id == organization_id
        ).first()
        if not db_persona:
            raise HTTPException(status_code=404, detail=f"Persona {persona_id} not found")
        
        update_data = persona_update.dict(exclude_unset=True)
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
    db: Session = Depends(get_db)
):
    """Delete a persona. Returns 409 if dependent records exist unless force=true."""
    db_persona = db.query(Persona).filter(
        Persona.id == persona_id,
        Persona.organization_id == organization_id
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
    db: Session = Depends(get_db)
):
    """Clone an existing persona to create a new one"""
    try:
        source_persona = db.query(Persona).filter(
            Persona.id == persona_id,
            Persona.organization_id == organization_id
        ).first()
        if not source_persona:
            raise HTTPException(status_code=404, detail=f"Persona {persona_id} not found")
        
        new_persona = Persona(
            organization_id=organization_id,
            name=clone_request.name if clone_request.name else f"{source_persona.name} (Copy)",
            gender=source_persona.gender,
            tts_provider=source_persona.tts_provider,
            tts_voice_id=source_persona.tts_voice_id,
            tts_voice_name=source_persona.tts_voice_name,
            is_custom=source_persona.is_custom,
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


# ============================================
# SEED DATA (Helper for demo)
# ============================================

@router.post("/seed-data", status_code=status.HTTP_201_CREATED)
async def seed_demo_data(
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Seed database with example personas and scenarios for the organization"""
    from app.models.database import Scenario
    
    try:
        personas_data = [
            {"name": "Grumpy Old Man", "gender": "male", "tts_provider": "openai", "tts_voice_id": "onyx", "tts_voice_name": "Onyx"},
            {"name": "Confused Senior", "gender": "female", "tts_provider": "openai", "tts_voice_id": "nova", "tts_voice_name": "Nova"},
            {"name": "Busy Professional", "gender": "neutral", "tts_provider": "openai", "tts_voice_id": "alloy", "tts_voice_name": "Alloy"},
            {"name": "Friendly Customer", "gender": "female", "tts_provider": "elevenlabs", "tts_voice_id": "21m00Tcm4TlvDq8ikWAM", "tts_voice_name": "Rachel"},
            {"name": "Angry Caller", "gender": "male", "tts_provider": "elevenlabs", "tts_voice_id": "TxGEqnHWrfWFTfGW9XjX", "tts_voice_name": "Josh"},
        ]
        
        # Check if personas already exist to avoid duplicates
        existing_persona_names = {p.name for p in db.query(Persona).filter(
            Persona.organization_id == organization_id,
            Persona.name.in_([p["name"] for p in personas_data])
        ).all()}
        
        personas_created = 0
        for persona_data in personas_data:
            if persona_data["name"] not in existing_persona_names:
                persona = Persona(organization_id=organization_id, **persona_data)
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
        
        # Check if scenarios already exist to avoid duplicates
        existing_scenario_names = {s.name for s in db.query(Scenario).filter(
            Scenario.organization_id == organization_id,
            Scenario.name.in_([s["name"] for s in scenarios_data])
        ).all()}
        
        scenarios_created = 0
        for scenario_data in scenarios_data:
            if scenario_data["name"] not in existing_scenario_names:
                scenario = Scenario(organization_id=organization_id, **scenario_data)
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

