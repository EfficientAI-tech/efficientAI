"""
Voice Playground API Routes
TTS A/B comparison: generate audio, blind test, and quality evaluation.
"""

import json
import random

import uuid as _uuid

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, File, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Dict, Any, List, Literal, Optional
from uuid import UUID
from pydantic import BaseModel, Field
from loguru import logger

from app.dependencies import get_db, get_organization_id, get_api_key, require_enterprise_feature
from app.models.database import (
    AIProvider,
    CallImport,
    CallImportRow,
    CustomTTSVoice,
    Integration,
    Organization,
    TTSComparison,
    TTSSample,
    TTSComparisonStatus,
    TTSSampleStatus,
    TTSReportJob,
    TTSReportJobStatus,
    TTSBlindTestShare,
    TTSBlindTestShareStatus,
    TTSBlindTestResponse,
    ModelProvider,
    VoiceBundle,
)
from app.services.ai.model_config_service import model_config_service
from app.services.storage.s3_service import s3_service
from app.services.ai.llm_service import llm_service
from app.services.reporting.voice_playground_report_service import voice_playground_report_service

router = APIRouter(
    prefix="/voice-playground",
    tags=["Voice Playground"],
    dependencies=[Depends(require_enterprise_feature("voice_playground"))],
)


def _generate_unique_simulation_id(db: Session, max_attempts: int = 100) -> str:
    """Generate a unique 6-digit numeric ID for a TTS comparison."""
    for _ in range(max_attempts):
        sid = f"{random.randint(100000, 999999)}"
        if not db.query(TTSComparison).filter(TTSComparison.simulation_id == sid).first():
            return sid
    raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to generate unique simulation ID")


# ======================================================================
# Static voice catalogues per provider
# ======================================================================

TTS_VOICES: Dict[str, List[Dict[str, str]]] = {
    "openai": [
        {"id": "alloy", "name": "Alloy", "gender": "Neutral", "accent": "American"},
        {"id": "ash", "name": "Ash", "gender": "Male", "accent": "American"},
        {"id": "coral", "name": "Coral", "gender": "Female", "accent": "American"},
        {"id": "echo", "name": "Echo", "gender": "Male", "accent": "American"},
        {"id": "fable", "name": "Fable", "gender": "Male", "accent": "British"},
        {"id": "onyx", "name": "Onyx", "gender": "Male", "accent": "American"},
        {"id": "nova", "name": "Nova", "gender": "Female", "accent": "American"},
        {"id": "sage", "name": "Sage", "gender": "Female", "accent": "American"},
        {"id": "shimmer", "name": "Shimmer", "gender": "Female", "accent": "American"},
    ],
    "elevenlabs": [
        {"id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel", "gender": "Female", "accent": "American"},
        {"id": "AZnzlk1XvdvUeBnXmlld", "name": "Domi", "gender": "Female", "accent": "American"},
        {"id": "EXAVITQu4vr4xnSDxMaL", "name": "Bella", "gender": "Female", "accent": "American"},
        {"id": "ErXwobaYiN019PkySvjV", "name": "Antoni", "gender": "Male", "accent": "American"},
        {"id": "MF3mGyEYCl7XYWbV9V6O", "name": "Elli", "gender": "Female", "accent": "American"},
        {"id": "TxGEqnHWrfWFTfGW9XjX", "name": "Josh", "gender": "Male", "accent": "American"},
        {"id": "VR6AewLTigWG4xSOukaG", "name": "Arnold", "gender": "Male", "accent": "American"},
        {"id": "pNInz6obpgDQGcFmaJgB", "name": "Adam", "gender": "Male", "accent": "American"},
        {"id": "yoZ06aMxZJJ28mfd3POQ", "name": "Sam", "gender": "Male", "accent": "American"},
        {"id": "jBpfuIE2acCO8z3wKNLl", "name": "Gigi", "gender": "Female", "accent": "American"},
    ],
    "cartesia": [
        {"id": "a0e99841-438c-4a64-b679-ae501e7d6091", "name": "Barbershop Man", "gender": "Male", "accent": "American"},
        {"id": "79a125e8-cd45-4c13-8a67-188112f4dd22", "name": "British Lady", "gender": "Female", "accent": "British"},
        {"id": "b7d50908-b17c-442d-ad8d-7c56a2ec8e67", "name": "Confident Woman", "gender": "Female", "accent": "American"},
        {"id": "c8605446-247c-4f39-993c-e0e2ee1c5112", "name": "Friendly Sidekick", "gender": "Male", "accent": "American"},
        {"id": "87748186-23bb-4571-ad1f-24094e1acbc5", "name": "Wise Guide", "gender": "Male", "accent": "American"},
        {"id": "41534e16-2966-4c6b-9670-111411def906", "name": "Nonfiction Man", "gender": "Male", "accent": "American"},
        {"id": "00a77add-48d5-4ef6-8157-71e5437b282d", "name": "Sportsman", "gender": "Male", "accent": "American"},
        {"id": "638efaaa-4d0c-442e-b701-3fae16aad012", "name": "Southern Woman", "gender": "Female", "accent": "American"},
    ],
    "deepgram": [
        {"id": "aura-asteria-en", "name": "Asteria", "gender": "Female", "accent": "American"},
        {"id": "aura-luna-en", "name": "Luna", "gender": "Female", "accent": "American"},
        {"id": "aura-stella-en", "name": "Stella", "gender": "Female", "accent": "American"},
        {"id": "aura-athena-en", "name": "Athena", "gender": "Female", "accent": "British"},
        {"id": "aura-hera-en", "name": "Hera", "gender": "Female", "accent": "American"},
        {"id": "aura-orion-en", "name": "Orion", "gender": "Male", "accent": "American"},
        {"id": "aura-arcas-en", "name": "Arcas", "gender": "Male", "accent": "American"},
        {"id": "aura-perseus-en", "name": "Perseus", "gender": "Male", "accent": "American"},
        {"id": "aura-angus-en", "name": "Angus", "gender": "Male", "accent": "Irish"},
        {"id": "aura-orpheus-en", "name": "Orpheus", "gender": "Male", "accent": "American"},
        {"id": "aura-helios-en", "name": "Helios", "gender": "Male", "accent": "British"},
        {"id": "aura-zeus-en", "name": "Zeus", "gender": "Male", "accent": "American"},
    ],
    "google": [
        {"id": "en-US-Neural2-A", "name": "Neural2 A", "gender": "Male", "accent": "American"},
        {"id": "en-US-Neural2-C", "name": "Neural2 C", "gender": "Female", "accent": "American"},
        {"id": "en-US-Neural2-D", "name": "Neural2 D", "gender": "Male", "accent": "American"},
        {"id": "en-US-Neural2-E", "name": "Neural2 E", "gender": "Female", "accent": "American"},
        {"id": "en-US-Neural2-F", "name": "Neural2 F", "gender": "Female", "accent": "American"},
        {"id": "en-US-Neural2-G", "name": "Neural2 G", "gender": "Female", "accent": "American"},
        {"id": "en-US-Neural2-H", "name": "Neural2 H", "gender": "Female", "accent": "American"},
        {"id": "en-US-Neural2-I", "name": "Neural2 I", "gender": "Male", "accent": "American"},
        {"id": "en-US-Neural2-J", "name": "Neural2 J", "gender": "Male", "accent": "American"},
    ],
    "sarvam": [
        {"id": "aditya", "name": "Aditya", "gender": "Male", "accent": "Indian"},
        {"id": "ritu", "name": "Ritu", "gender": "Female", "accent": "Indian"},
        {"id": "ashutosh", "name": "Ashutosh", "gender": "Male", "accent": "Indian"},
        {"id": "priya", "name": "Priya", "gender": "Female", "accent": "Indian"},
        {"id": "neha", "name": "Neha", "gender": "Female", "accent": "Indian"},
        {"id": "rahul", "name": "Rahul", "gender": "Male", "accent": "Indian"},
        {"id": "pooja", "name": "Pooja", "gender": "Female", "accent": "Indian"},
        {"id": "rohan", "name": "Rohan", "gender": "Male", "accent": "Indian"},
        {"id": "simran", "name": "Simran", "gender": "Female", "accent": "Indian"},
        {"id": "kavya", "name": "Kavya", "gender": "Female", "accent": "Indian"},
    ],
    "voicemaker": [
        {"id": "ai3-Jony", "name": "Jony", "gender": "Male", "accent": "American", "language_code": "en-US"},
        {"id": "ai2-Katie", "name": "Katie", "gender": "Female", "accent": "American", "language_code": "en-US"},
        {"id": "ai1-Joanna", "name": "Joanna", "gender": "Female", "accent": "American", "language_code": "en-US"},
        {"id": "pro1-Catherine", "name": "Catherine", "gender": "Female", "accent": "British", "language_code": "en-GB"},
        {"id": "proplus-Richard", "name": "Richard", "gender": "Male", "accent": "British", "language_code": "en-GB"},
        {"id": "proplus-Emma", "name": "Emma", "gender": "Female", "accent": "British", "language_code": "en-GB"},
        {"id": "ai3-Ana", "name": "Ana", "gender": "Female", "accent": "Spanish", "language_code": "es-ES"},
        {"id": "ai3-Lea", "name": "Lea", "gender": "Female", "accent": "German", "language_code": "de-DE"},
        {"id": "ai3-Keiko", "name": "Keiko", "gender": "Female", "accent": "Japanese", "language_code": "ja-JP"},
        {"id": "ai3-Liang", "name": "Liang", "gender": "Male", "accent": "Chinese", "language_code": "zh-CN"},
    ],
    "smallest": [
        {"id": "daniel", "name": "Daniel", "gender": "Male", "accent": "American"},
    ],
}

def _get_tts_models_by_provider() -> Dict[str, List[str]]:
    """Build provider -> TTS models map from models.json config."""
    providers_with_tts: Dict[str, List[str]] = {}
    for provider_enum in ModelProvider:
        try:
            tts_models = model_config_service.get_models_by_type(provider_enum, "tts")
        except Exception:
            tts_models = []
        if tts_models:
            providers_with_tts[provider_enum.value] = tts_models
    return providers_with_tts

PROVIDER_SAMPLE_RATES: Dict[str, List[int]] = {
    "elevenlabs": [8000, 16000, 22050, 24000, 44100],
    "cartesia": [8000, 16000, 22050, 24000, 44100],
    "deepgram": [8000, 16000, 24000, 48000],
    # Murf stream API valid sample rates.
    "murf": [8000, 16000, 24000, 44100, 48000],
    "voicemaker": [8000, 16000, 22050, 24000, 44100, 48000],
    "smallest": [8000, 16000, 24000],
}

# ======================================================================
# Schemas
# ======================================================================


class BenchmarkSideConfig(BaseModel):
    """Per-side configuration for the benchmark flow.

    A side can be a TTS provider (default), a set of recordings pulled from
    call_import_rows, or a set of uploaded audio files. For non-tts sources
    the audio is reused as-is and the worker skips synthesis.
    """
    source_type: Literal["tts", "recording", "upload"] = "tts"
    # TTS-only fields:
    provider: Optional[str] = None
    model: Optional[str] = None
    voices: Optional[List[Dict[str, Any]]] = None
    # Recording / upload fields (one entry per "voice slot" / per sample_index
    # depending on the side; the API picks the first per sample_index):
    call_import_row_ids: Optional[List[UUID]] = None
    upload_s3_keys: Optional[List[str]] = None


class BlindTestPairAudioRef(BaseModel):
    """Audio reference for one side of a blind-test pair."""
    type: Literal["recording", "upload", "tts_sample"]
    call_import_row_id: Optional[UUID] = None
    upload_s3_key: Optional[str] = None
    tts_sample_id: Optional[UUID] = None
    label: Optional[str] = None


class BlindTestPair(BaseModel):
    text: Optional[str] = None
    x: BlindTestPairAudioRef
    y: BlindTestPairAudioRef


class TTSComparisonCreate(BaseModel):
    """Create a Voice Playground comparison.

    Supports two modes:
      * mode="benchmark" (default): traditional A/B benchmark. Each side may
        be a TTS provider, recordings from CallImports, or uploaded audio.
        Backwards-compatible with the legacy top-level provider_a/voices_a
        fields when side_a/side_b are omitted.
      * mode="blind_test_only": no TTS generation. The caller provides a list
        of blind-test pairs whose audio comes from existing recordings,
        uploads, or past TTS samples.
    """
    name: Optional[str] = None
    mode: Literal["benchmark", "blind_test_only"] = "benchmark"

    # ---- Legacy / top-level benchmark fields (kept for backwards compat) --
    provider_a: Optional[str] = None
    model_a: Optional[str] = None
    voices_a: Optional[List[Dict[str, Any]]] = None
    provider_b: Optional[str] = None
    model_b: Optional[str] = None
    voices_b: Optional[List[Dict[str, Any]]] = None

    # ---- New per-side benchmark config (preferred when present) ----------
    side_a: Optional[BenchmarkSideConfig] = None
    side_b: Optional[BenchmarkSideConfig] = None

    # ---- Common ----------------------------------------------------------
    sample_texts: Optional[List[str]] = None
    num_runs: int = 1
    eval_stt_provider: Optional[str] = None
    eval_stt_model: Optional[str] = None

    # ---- blind_test_only fields ------------------------------------------
    pairs: Optional[List[BlindTestPair]] = None


class BlindTestSubmit(BaseModel):
    results: List[Dict[str, Any]]
    # Each entry: {"sample_index": 0, "preferred": "A" | "B", "voice_a_id": "...", "voice_b_id": "..."}


class BlindTestCustomMetric(BaseModel):
    """A single metric raters can fill in for both A and B per sample.

    type='rating' → numeric scale (1..scale), recorded per A and per B.
    type='comment' → free-text per sample (not per side).
    """
    key: str
    label: str
    type: str  # 'rating' | 'comment'
    scale: Optional[int] = None  # required for rating; default 5


class BlindTestShareCreate(BaseModel):
    title: str
    description: Optional[str] = None
    custom_metrics: List[BlindTestCustomMetric] = []


class BlindTestSharePatch(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    custom_metrics: Optional[List[BlindTestCustomMetric]] = None
    status: Optional[str] = None  # 'open' | 'closed'


class GenerateSamplesRequest(BaseModel):
    voice_bundle_id: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    scenario: Optional[str] = None
    count: int = 5
    length: Optional[str] = "short"  # "short" | "medium" | "long" | "paragraph"
    temperature: Optional[float] = 0.8


class CustomVoiceCreate(BaseModel):
    provider: str
    voice_id: str
    name: str
    gender: Optional[str] = None
    accent: Optional[str] = None
    description: Optional[str] = None


class CustomVoiceUpdate(BaseModel):
    voice_id: Optional[str] = None
    name: Optional[str] = None
    gender: Optional[str] = None
    accent: Optional[str] = None
    description: Optional[str] = None


class TTSReportOptions(BaseModel):
    show_runs: bool = True
    min_runs_to_show: int = 100
    include_latency: bool = True
    include_ttfb: bool = True
    include_endpoint: bool = True
    include_naturalness: bool = True
    include_hallucination: bool = True
    include_prosody: bool = True
    include_arousal: bool = True
    include_valence: bool = True
    include_cer: bool = True
    include_wer: bool = True
    include_hallucination_examples: bool = True
    hallucination_examples_limit: int = 5
    include_disclaimer_sections: bool = True
    include_methodology_sections: bool = False
    zone_threshold_overrides: Optional[Dict[str, Dict[str, float]]] = None


class TTSReportJobCreate(BaseModel):
    report_options: Optional[TTSReportOptions] = None


class VoicePlaygroundThresholdDefaultsUpdate(BaseModel):
    zone_threshold_overrides: Optional[Dict[str, Dict[str, float]]] = None
    reset_to_system_defaults: bool = False


DEFAULT_ZONE_THRESHOLD_OVERRIDES: Dict[str, Dict[str, float]] = {
    "avg_mos": {"neutral_min": 3.0, "good_min": 4.0},
    "avg_prosody": {"neutral_min": 0.4, "good_min": 0.7},
    "avg_valence": {"neutral_min": -0.2, "good_min": 0.3},
    "avg_arousal": {"neutral_min": 0.4, "good_min": 0.7},
    "avg_wer": {"good_max": 0.1, "neutral_max": 0.25},
    "avg_cer": {"good_max": 0.08, "neutral_max": 0.2},
    "avg_ttfb_ms": {"good_max": 350.0, "neutral_max": 800.0},
    "avg_latency_ms": {"good_max": 1500.0, "neutral_max": 3000.0},
}


SAMPLE_GENERATION_SYSTEM_PROMPT = """You are an expert at creating realistic text-to-speech sample scripts. \
Generate natural-sounding text that would be spoken aloud by a voice AI agent, \
varied in tone and content, and suitable for evaluating TTS voice quality. \
Include a mix of: greetings, questions, informational statements, numbers/dates, and emotional expressions. \
Return ONLY a JSON array of strings, with no additional text or markdown formatting."""

SAMPLE_LENGTH_INSTRUCTIONS = {
    "short": "Each sample should be exactly 1 sentence (10-25 words).",
    "medium": "Each sample should be 2-3 sentences (30-60 words).",
    "long": "Each sample should be 4-6 sentences (80-150 words), forming a coherent mini-monologue.",
    "paragraph": "Each sample should be a full paragraph of 7-10 sentences (150-250 words), like a complete agent response with context, explanation, and follow-up.",
}

SAMPLE_LENGTH_MAX_TOKENS = {
    "short": 1500,
    "medium": 2500,
    "long": 4000,
    "paragraph": 6000,
}


# ======================================================================
# Endpoints
# ======================================================================


def _serialize_custom_voice(voice: CustomTTSVoice) -> Dict[str, Any]:
    return {
        "id": str(voice.id),
        "provider": voice.provider,
        "voice_id": voice.voice_id,
        "name": voice.name,
        "gender": voice.gender or "Unknown",
        "accent": voice.accent or "Unknown",
        "description": voice.description,
        "is_custom": True,
        "created_at": voice.created_at.isoformat() if voice.created_at else None,
        "updated_at": voice.updated_at.isoformat() if voice.updated_at else None,
    }


@router.post("/generate-samples", operation_id="generateTTSSamples")
async def generate_sample_texts(
    data: GenerateSamplesRequest,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Generate TTS sample texts using an LLM from a voice bundle or specified provider."""
    import json as json_mod

    llm_provider_str = data.provider
    llm_model_str = data.model
    temperature = data.temperature or 0.8

    if data.voice_bundle_id:
        bundle = db.query(VoiceBundle).filter(
            VoiceBundle.id == data.voice_bundle_id,
            VoiceBundle.organization_id == organization_id,
        ).first()
        if not bundle:
            raise HTTPException(404, "Voice bundle not found")
        if not bundle.llm_provider or not bundle.llm_model:
            raise HTTPException(400, "Selected voice bundle has no LLM configured")
        llm_provider_str = bundle.llm_provider
        llm_model_str = bundle.llm_model
        if bundle.llm_temperature is not None:
            temperature = bundle.llm_temperature

    if not llm_provider_str or not llm_model_str:
        raise HTTPException(400, "Either voice_bundle_id or both provider and model are required")

    try:
        provider_enum = ModelProvider(llm_provider_str.lower())
    except ValueError:
        raise HTTPException(400, f"Unsupported LLM provider: {llm_provider_str}")

    count = max(1, min(data.count, 20))
    length = data.length if data.length in SAMPLE_LENGTH_INSTRUCTIONS else "short"
    scenario_text = data.scenario or "general customer service and voice assistant interactions"
    length_instruction = SAMPLE_LENGTH_INSTRUCTIONS[length]
    max_tokens = SAMPLE_LENGTH_MAX_TOKENS[length]

    user_prompt = (
        f"Generate exactly {count} TTS sample texts for the following scenario:\n"
        f"Scenario: {scenario_text}\n\n"
        f"Length requirement: {length_instruction}\n\n"
        f"Return a JSON array of {count} strings."
    )

    messages = [
        {"role": "system", "content": SAMPLE_GENERATION_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    try:
        result = llm_service.generate_response(
            messages=messages,
            llm_provider=provider_enum,
            llm_model=llm_model_str,
            organization_id=organization_id,
            db=db,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as e:
        logger.error(f"[VoicePlayground] LLM generation failed: {e}")
        raise HTTPException(500, f"LLM generation failed: {str(e)}")

    raw_text = result.get("text", "").strip()

    # Parse JSON array from response, handling markdown code fences
    if raw_text.startswith("```"):
        lines = raw_text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw_text = "\n".join(lines).strip()

    try:
        samples = json_mod.loads(raw_text)
        if not isinstance(samples, list):
            raise ValueError("Expected a JSON array")
        samples = [str(s).strip() for s in samples if s]
    except (json_mod.JSONDecodeError, ValueError):
        samples = [line.strip().strip('"').strip("'") for line in raw_text.split("\n") if line.strip() and not line.strip().startswith("[") and not line.strip().startswith("]")]

    return {
        "samples": samples[:count],
        "provider": llm_provider_str,
        "model": llm_model_str,
    }


@router.get("/custom-voices", operation_id="listCustomTTSVoices")
async def list_custom_tts_voices(
    provider: Optional[str] = None,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    query = db.query(CustomTTSVoice).filter(CustomTTSVoice.organization_id == organization_id)
    if provider:
        query = query.filter(CustomTTSVoice.provider == provider.lower())
    voices = query.order_by(CustomTTSVoice.provider.asc(), CustomTTSVoice.name.asc()).all()
    return [_serialize_custom_voice(v) for v in voices]


@router.post("/custom-voices", operation_id="createCustomTTSVoice")
async def create_custom_tts_voice(
    data: CustomVoiceCreate,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    provider = data.provider.strip().lower()
    voice_id = data.voice_id.strip()
    name = data.name.strip()

    tts_models_by_provider = _get_tts_models_by_provider()
    if provider not in tts_models_by_provider:
        raise HTTPException(400, f"Unsupported TTS provider: {provider}")
    if not voice_id:
        raise HTTPException(400, "voice_id is required")
    if not name:
        raise HTTPException(400, "name is required")

    existing = db.query(CustomTTSVoice).filter(
        CustomTTSVoice.organization_id == organization_id,
        CustomTTSVoice.provider == provider,
        CustomTTSVoice.voice_id == voice_id,
    ).first()
    if existing:
        raise HTTPException(409, f"Custom voice already exists for provider '{provider}' and voice_id '{voice_id}'")

    voice = CustomTTSVoice(
        organization_id=organization_id,
        provider=provider,
        voice_id=voice_id,
        name=name,
        gender=data.gender.strip() if data.gender else None,
        accent=data.accent.strip() if data.accent else None,
        description=data.description.strip() if data.description else None,
    )
    db.add(voice)
    db.commit()
    db.refresh(voice)
    return _serialize_custom_voice(voice)


@router.put("/custom-voices/{custom_voice_id}", operation_id="updateCustomTTSVoice")
async def update_custom_tts_voice(
    custom_voice_id: UUID,
    data: CustomVoiceUpdate,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    voice = db.query(CustomTTSVoice).filter(
        CustomTTSVoice.id == custom_voice_id,
        CustomTTSVoice.organization_id == organization_id,
    ).first()
    if not voice:
        raise HTTPException(404, "Custom voice not found")

    if data.voice_id is not None:
        cleaned_voice_id = data.voice_id.strip()
        if not cleaned_voice_id:
            raise HTTPException(400, "voice_id cannot be empty")
        duplicate = db.query(CustomTTSVoice).filter(
            CustomTTSVoice.organization_id == organization_id,
            CustomTTSVoice.provider == voice.provider,
            CustomTTSVoice.voice_id == cleaned_voice_id,
            CustomTTSVoice.id != voice.id,
        ).first()
        if duplicate:
            raise HTTPException(409, f"Custom voice already exists for provider '{voice.provider}' and voice_id '{cleaned_voice_id}'")
        voice.voice_id = cleaned_voice_id

    if data.name is not None:
        cleaned_name = data.name.strip()
        if not cleaned_name:
            raise HTTPException(400, "name cannot be empty")
        voice.name = cleaned_name
    if data.gender is not None:
        voice.gender = data.gender.strip() or None
    if data.accent is not None:
        voice.accent = data.accent.strip() or None
    if data.description is not None:
        voice.description = data.description.strip() or None

    db.commit()
    db.refresh(voice)
    return _serialize_custom_voice(voice)


@router.delete("/custom-voices/{custom_voice_id}", operation_id="deleteCustomTTSVoice")
async def delete_custom_tts_voice(
    custom_voice_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    voice = db.query(CustomTTSVoice).filter(
        CustomTTSVoice.id == custom_voice_id,
        CustomTTSVoice.organization_id == organization_id,
    ).first()
    if not voice:
        raise HTTPException(404, "Custom voice not found")
    db.delete(voice)
    db.commit()
    return {"message": "Custom voice deleted"}


@router.get("/tts-providers", operation_id="listTTSProviders")
async def list_tts_providers(
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """List TTS providers that have an active API key configured."""
    tts_models_by_provider = _get_tts_models_by_provider()

    # Gather active AI providers
    ai_providers = db.query(AIProvider).filter(
        AIProvider.organization_id == organization_id,
        AIProvider.is_active == True,
    ).all()

    active_provider_keys = set()
    for ap in ai_providers:
        pval = ap.provider.lower() if ap.provider else ""
        if pval in tts_models_by_provider:
            active_provider_keys.add(pval)

    # Also check Integration table for cartesia / elevenlabs / deepgram
    integrations = db.query(Integration).filter(
        Integration.organization_id == organization_id,
        Integration.is_active == True,
    ).all()
    for integ in integrations:
        pval = integ.platform.lower() if integ.platform else ""
        if pval in tts_models_by_provider:
            active_provider_keys.add(pval)

    custom_voices = db.query(CustomTTSVoice).filter(
        CustomTTSVoice.organization_id == organization_id
    ).all()
    custom_voices_by_provider: Dict[str, List[CustomTTSVoice]] = {}
    for cv in custom_voices:
        custom_voices_by_provider.setdefault(cv.provider, []).append(cv)

    result = []
    for provider_key in sorted(active_provider_keys):
        tts_models = tts_models_by_provider.get(provider_key, [])

        if not tts_models:
            continue

        static_voices = TTS_VOICES.get(provider_key, [])
        model_voices_map: Dict[str, Dict[str, Dict[str, Any]]] = {}
        model_config_voices: List[Dict[str, Any]] = []
        for model_name in tts_models:
            voices_for_model = model_config_service.get_voices_for_model(model_name)
            model_voices_map[model_name] = {}
            for mv in voices_for_model:
                vid = mv.get("id")
                if not vid:
                    continue
                normalized_voice = {
                    "id": vid,
                    "name": mv.get("name", vid),
                    "gender": mv.get("gender", "Unknown"),
                    "accent": mv.get("accent", "Unknown"),
                    "is_custom": False,
                }
                model_voices_map[model_name][vid] = normalized_voice
                model_config_voices.append(normalized_voice)
        merged_voice_map: Dict[str, Dict[str, Any]] = {
            v["id"]: {
                "id": v["id"],
                "name": v["name"],
                "gender": v.get("gender", "Unknown"),
                "accent": v.get("accent", "Unknown"),
                "is_custom": False,
            }
            for v in static_voices
        }
        for mv in model_config_voices:
            vid = mv.get("id")
            if not vid:
                continue
            merged_voice_map[vid] = {
                "id": vid,
                "name": mv.get("name", vid),
                "gender": mv.get("gender", "Unknown"),
                "accent": mv.get("accent", "Unknown"),
                "is_custom": False,
            }
        for cv in custom_voices_by_provider.get(provider_key, []):
            custom_voice = {
                "id": cv.voice_id,
                "name": cv.name,
                "gender": cv.gender or "Unknown",
                "accent": cv.accent or "Unknown",
                "description": cv.description,
                "is_custom": True,
                "custom_voice_id": str(cv.id),
            }
            merged_voice_map[cv.voice_id] = custom_voice
            # Custom voices should be available across all models for a provider.
            for model_name in tts_models:
                model_voices_map.setdefault(model_name, {})[cv.voice_id] = custom_voice

        voices = sorted(list(merged_voice_map.values()), key=lambda v: (0 if v.get("is_custom") else 1, v["name"].lower()))
        model_voices = {
            model_name: sorted(list(voice_map.values()), key=lambda v: (0 if v.get("is_custom") else 1, v["name"].lower()))
            for model_name, voice_map in model_voices_map.items()
        }
        sample_rates = PROVIDER_SAMPLE_RATES.get(provider_key, [])

        result.append({
            "provider": provider_key,
            "models": tts_models,
            "voices": voices,
            "model_voices": model_voices,
            "supported_sample_rates": sample_rates,
        })

    return result


def _normalize_benchmark_side(
    side_cfg: Optional[BenchmarkSideConfig],
    legacy_provider: Optional[str],
    legacy_model: Optional[str],
    legacy_voices: Optional[List[Dict[str, Any]]],
) -> Optional[BenchmarkSideConfig]:
    """Merge new-style side_x and legacy provider_x/voices_x payloads.

    Returns None when the side is entirely empty (allowed for side_b).
    """
    if side_cfg is not None:
        return side_cfg
    if (legacy_provider or "").strip() or legacy_voices:
        return BenchmarkSideConfig(
            source_type="tts",
            provider=(legacy_provider or "").strip() or None,
            model=(legacy_model or "").strip() or None,
            voices=legacy_voices or [],
        )
    return None


def _load_call_import_row(
    row_id: UUID, organization_id: UUID, db: Session
) -> CallImportRow:
    row = (
        db.query(CallImportRow)
        .filter(
            CallImportRow.id == row_id,
            CallImportRow.organization_id == organization_id,
        )
        .first()
    )
    if not row:
        raise HTTPException(404, f"Call import row {row_id} not found")
    if not row.recording_s3_key:
        raise HTTPException(
            400, f"Call import row {row_id} has no recording stored in S3 yet"
        )
    return row


def _validate_upload_key(key: str, organization_id: UUID) -> str:
    """Ensure an upload S3 key belongs to this org's voicePlayground/uploads/ prefix."""
    expected_prefix = (
        f"{s3_service.prefix}organizations/{organization_id}/voicePlayground/uploads/"
    )
    if not key.startswith(expected_prefix):
        raise HTTPException(
            400,
            f"Upload key '{key}' must be under the org's voice playground uploads prefix",
        )
    return key


def _resolve_audio_ref(
    ref: BlindTestPairAudioRef, organization_id: UUID, db: Session
) -> Dict[str, Any]:
    """Resolve a blind-test audio ref to a dict with audio_s3_key / metadata.

    Returned shape: {
        audio_s3_key, source_type, source_ref_id, voice_id, voice_name,
        provider, model, label, duration_seconds (optional)
    }
    """
    if ref.type == "recording":
        if not ref.call_import_row_id:
            raise HTTPException(400, "call_import_row_id is required for recording refs")
        row = _load_call_import_row(ref.call_import_row_id, organization_id, db)
        return {
            "audio_s3_key": row.recording_s3_key,
            "source_type": "recording",
            "source_ref_id": row.id,
            "voice_id": f"call:{row.external_call_id}",
            "voice_name": ref.label or row.external_call_id,
            "provider": None,
            "model": None,
            "label": ref.label or row.external_call_id,
        }

    if ref.type == "upload":
        if not ref.upload_s3_key:
            raise HTTPException(400, "upload_s3_key is required for upload refs")
        key = _validate_upload_key(ref.upload_s3_key, organization_id)
        return {
            "audio_s3_key": key,
            "source_type": "upload",
            "source_ref_id": None,
            "voice_id": "upload",
            "voice_name": ref.label or "Uploaded audio",
            "provider": None,
            "model": None,
            "label": ref.label or "Uploaded audio",
        }

    if ref.type == "tts_sample":
        if not ref.tts_sample_id:
            raise HTTPException(400, "tts_sample_id is required for tts_sample refs")
        sample = (
            db.query(TTSSample)
            .filter(
                TTSSample.id == ref.tts_sample_id,
                TTSSample.organization_id == organization_id,
            )
            .first()
        )
        if not sample:
            raise HTTPException(404, f"TTS sample {ref.tts_sample_id} not found")
        if not sample.audio_s3_key:
            raise HTTPException(
                400, f"TTS sample {ref.tts_sample_id} has no audio yet"
            )
        return {
            "audio_s3_key": sample.audio_s3_key,
            "source_type": "tts",
            "source_ref_id": sample.id,
            "voice_id": sample.voice_id,
            "voice_name": sample.voice_name or sample.voice_id,
            "provider": sample.provider,
            "model": sample.model,
            "label": ref.label
            or f"{sample.provider}/{sample.voice_name or sample.voice_id}",
        }

    raise HTTPException(400, f"Unsupported audio ref type: {ref.type}")


def _build_benchmark_side_samples(
    *,
    comparison: TTSComparison,
    side_label: str,
    cfg: BenchmarkSideConfig,
    sample_texts: List[str],
    num_runs: int,
    organization_id: UUID,
    db: Session,
) -> None:
    """Create TTSSample rows for one benchmark side.

    For source_type='tts': one sample per voice/text/run with status PENDING
    (worker will synthesize). For source_type='recording'/'upload': samples
    are pre-resolved with audio_s3_key and marked COMPLETED.
    """
    if cfg.source_type == "tts":
        provider = (cfg.provider or "").strip()
        model = (cfg.model or "").strip()
        voices = cfg.voices or []
        if not provider or not model:
            raise HTTPException(
                400, f"Side {side_label}: provider and model are required for TTS source"
            )
        if not voices:
            raise HTTPException(
                400, f"Side {side_label}: at least one voice is required for TTS source"
            )
        for run in range(num_runs):
            for idx, txt in enumerate(sample_texts):
                for voice in voices:
                    vid = voice["id"] if isinstance(voice, dict) else voice
                    vname = (
                        voice.get("name", vid) if isinstance(voice, dict) else vid
                    )
                    db.add(
                        TTSSample(
                            comparison_id=comparison.id,
                            organization_id=organization_id,
                            provider=provider,
                            model=model,
                            voice_id=vid,
                            voice_name=vname,
                            side=side_label,
                            sample_index=idx,
                            run_index=run,
                            text=txt,
                            status=TTSSampleStatus.PENDING.value,
                            source_type="tts",
                        )
                    )
        return

    # Non-tts side: resolve a flat list of audio refs and pair them with
    # sample_texts by index. The caller is expected to provide one audio
    # source per sample_text (extras are ignored, missing ones produce an
    # error so the user notices the mismatch).
    if cfg.source_type == "recording":
        row_ids = cfg.call_import_row_ids or []
        if len(row_ids) < len(sample_texts):
            raise HTTPException(
                400,
                f"Side {side_label}: need at least {len(sample_texts)} call_import_row_ids "
                f"to match sample_texts (got {len(row_ids)})",
            )
        resolved = [
            _load_call_import_row(rid, organization_id, db) for rid in row_ids[: len(sample_texts)]
        ]
        for run in range(num_runs):
            for idx, txt in enumerate(sample_texts):
                row = resolved[idx]
                db.add(
                    TTSSample(
                        comparison_id=comparison.id,
                        organization_id=organization_id,
                        provider=None,
                        model=None,
                        voice_id=f"call:{row.external_call_id}",
                        voice_name=row.external_call_id,
                        side=side_label,
                        sample_index=idx,
                        run_index=run,
                        text=txt,
                        audio_s3_key=row.recording_s3_key,
                        status=TTSSampleStatus.COMPLETED.value,
                        source_type="recording",
                        source_ref_id=row.id,
                    )
                )
        return

    if cfg.source_type == "upload":
        keys = cfg.upload_s3_keys or []
        if len(keys) < len(sample_texts):
            raise HTTPException(
                400,
                f"Side {side_label}: need at least {len(sample_texts)} upload_s3_keys "
                f"to match sample_texts (got {len(keys)})",
            )
        validated = [_validate_upload_key(k, organization_id) for k in keys[: len(sample_texts)]]
        for run in range(num_runs):
            for idx, txt in enumerate(sample_texts):
                key = validated[idx]
                db.add(
                    TTSSample(
                        comparison_id=comparison.id,
                        organization_id=organization_id,
                        provider=None,
                        model=None,
                        voice_id="upload",
                        voice_name="Uploaded audio",
                        side=side_label,
                        sample_index=idx,
                        run_index=run,
                        text=txt,
                        audio_s3_key=key,
                        status=TTSSampleStatus.COMPLETED.value,
                        source_type="upload",
                    )
                )
        return

    raise HTTPException(400, f"Unsupported source_type for side {side_label}: {cfg.source_type}")


@router.get("/call-import-rows", operation_id="listVoicePlaygroundCallImportRows")
async def list_voice_playground_call_import_rows(
    call_import_id: Optional[UUID] = None,
    with_recording: bool = True,
    skip: int = 0,
    limit: int = 100,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """List call_import_rows for use as Voice Playground audio sources."""
    query = (
        db.query(CallImportRow, CallImport.original_filename)
        .join(CallImport, CallImportRow.call_import_id == CallImport.id)
        .filter(CallImportRow.organization_id == organization_id)
    )
    if call_import_id is not None:
        query = query.filter(CallImportRow.call_import_id == call_import_id)
    if with_recording:
        query = query.filter(CallImportRow.recording_s3_key.isnot(None))

    total = query.count()
    rows = (
        query.order_by(CallImportRow.created_at.desc())
        .offset(max(0, skip))
        .limit(min(max(1, limit), 500))
        .all()
    )

    items = []
    for row, original_filename in rows:
        items.append(
            {
                "id": str(row.id),
                "call_import_id": str(row.call_import_id),
                "call_import_filename": original_filename,
                "external_call_id": row.external_call_id,
                "transcript": row.transcript,
                "recording_s3_key": row.recording_s3_key,
                "has_recording": bool(row.recording_s3_key),
                "status": row.status.value if hasattr(row.status, "value") else row.status,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )

    return {"items": items, "total": total, "skip": skip, "limit": limit}


@router.post("/uploads", operation_id="uploadVoicePlaygroundAudio")
async def upload_voice_playground_audio(
    file: UploadFile = File(...),
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Upload an audio file (mp3/wav/etc.) for use in a comparison.

    Stores the file under the org's voicePlayground/uploads/ prefix and
    returns the S3 key + a presigned URL for immediate playback. The S3 key
    can later be passed in `upload_s3_keys` (benchmark) or `upload_s3_key`
    (blind_test_only pair refs).
    """
    if not file.filename:
        raise HTTPException(400, "Filename is required")

    allowed_exts = {"mp3", "wav", "flac", "ogg", "m4a", "aac", "webm"}
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "mp3"
    if ext not in allowed_exts:
        raise HTTPException(400, f"Unsupported audio format '{ext}'. Allowed: {sorted(allowed_exts)}")

    content_type_map = {
        "wav": "audio/wav",
        "mp3": "audio/mpeg",
        "flac": "audio/flac",
        "m4a": "audio/mp4",
        "aac": "audio/aac",
        "ogg": "audio/ogg",
        "webm": "audio/webm",
    }
    content_type = content_type_map.get(ext, file.content_type or "application/octet-stream")

    contents = await file.read()
    if not contents:
        raise HTTPException(400, "Uploaded file is empty")

    max_bytes = 25 * 1024 * 1024
    if len(contents) > max_bytes:
        raise HTTPException(413, f"File too large (max {max_bytes // (1024 * 1024)} MB)")

    upload_id = _uuid.uuid4()
    key = (
        f"{s3_service.prefix}organizations/{organization_id}/voicePlayground/uploads/"
        f"{upload_id}.{ext}"
    )

    try:
        s3_service.upload_file_by_key(
            file_content=contents, key=key, content_type=content_type
        )
    except Exception as e:
        logger.error(f"[VoicePlayground] Upload failed: {e}")
        raise HTTPException(500, f"Failed to store uploaded audio: {e}")

    try:
        presigned = s3_service.generate_presigned_url_by_key(key, expiration=3600)
    except Exception:
        presigned = None

    return {
        "s3_key": key,
        "presigned_url": presigned,
        "filename": file.filename,
        "size_bytes": len(contents),
        "content_type": content_type,
    }


@router.post("/comparisons", operation_id="createTTSComparison")
async def create_comparison(
    data: TTSComparisonCreate,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Create a Voice Playground comparison (benchmark or blind_test_only)."""
    num_runs = max(1, min(data.num_runs, 10))
    simulation_id = _generate_unique_simulation_id(db)

    if data.mode == "blind_test_only":
        if not data.pairs:
            raise HTTPException(400, "At least one pair is required for blind_test_only")

        sample_texts: List[str] = [
            (p.text or "").strip() or f"Pair {idx + 1}" for idx, p in enumerate(data.pairs)
        ]

        comparison = TTSComparison(
            organization_id=organization_id,
            simulation_id=simulation_id,
            name=data.name or "Blind test",
            status=TTSComparisonStatus.PENDING.value,
            mode="blind_test_only",
            provider_a=None,
            model_a=None,
            voices_a=[],
            provider_b=None,
            model_b=None,
            voices_b=[],
            sample_texts=sample_texts,
            num_runs=1,
            eval_stt_provider=data.eval_stt_provider,
            eval_stt_model=data.eval_stt_model,
        )
        db.add(comparison)
        db.flush()

        # Resolve all refs first so we can populate provider/voices summary.
        for idx, pair in enumerate(data.pairs):
            x = _resolve_audio_ref(pair.x, organization_id, db)
            y = _resolve_audio_ref(pair.y, organization_id, db)

            for letter, info in [("A", x), ("B", y)]:
                db.add(
                    TTSSample(
                        comparison_id=comparison.id,
                        organization_id=organization_id,
                        provider=info["provider"],
                        model=info["model"],
                        voice_id=info["voice_id"],
                        voice_name=info["voice_name"],
                        side=letter,
                        sample_index=idx,
                        run_index=0,
                        text=sample_texts[idx],
                        audio_s3_key=info["audio_s3_key"],
                        status=TTSSampleStatus.COMPLETED.value,
                        source_type=info["source_type"],
                        source_ref_id=info["source_ref_id"],
                    )
                )

        # Populate the legacy provider_a/voices_a summary from the first pair
        # so the share modal / results view show meaningful labels.
        first_x = _resolve_audio_ref(data.pairs[0].x, organization_id, db)
        first_y = _resolve_audio_ref(data.pairs[0].y, organization_id, db)
        comparison.provider_a = first_x["provider"] or first_x["source_type"]
        comparison.model_a = first_x["model"]
        comparison.voices_a = [
            {"id": first_x["voice_id"], "name": first_x["voice_name"]}
        ]
        comparison.provider_b = first_y["provider"] or first_y["source_type"]
        comparison.model_b = first_y["model"]
        comparison.voices_b = [
            {"id": first_y["voice_id"], "name": first_y["voice_name"]}
        ]
        comparison.status = TTSComparisonStatus.COMPLETED.value

        db.commit()
        db.refresh(comparison)
        return _serialize_comparison(comparison, db)

    # ---------- benchmark mode ----------
    if not data.sample_texts:
        raise HTTPException(400, "At least one sample text is required")

    side_a_cfg = _normalize_benchmark_side(
        data.side_a, data.provider_a, data.model_a, data.voices_a
    )
    side_b_cfg = _normalize_benchmark_side(
        data.side_b, data.provider_b, data.model_b, data.voices_b
    )

    if side_a_cfg is None:
        raise HTTPException(400, "Side A configuration is required for benchmark mode")

    name = data.name or _build_benchmark_name(side_a_cfg, side_b_cfg)

    comparison = TTSComparison(
        organization_id=organization_id,
        simulation_id=simulation_id,
        name=name,
        status=TTSComparisonStatus.PENDING.value,
        mode="benchmark",
        provider_a=(side_a_cfg.provider or "").strip() or None if side_a_cfg.source_type == "tts" else None,
        model_a=(side_a_cfg.model or "").strip() or None if side_a_cfg.source_type == "tts" else None,
        voices_a=(side_a_cfg.voices or []) if side_a_cfg.source_type == "tts" else [],
        provider_b=(
            (side_b_cfg.provider or "").strip() or None
            if side_b_cfg and side_b_cfg.source_type == "tts"
            else None
        ),
        model_b=(
            (side_b_cfg.model or "").strip() or None
            if side_b_cfg and side_b_cfg.source_type == "tts"
            else None
        ),
        voices_b=(
            (side_b_cfg.voices or [])
            if (side_b_cfg and side_b_cfg.source_type == "tts")
            else []
        ),
        sample_texts=data.sample_texts,
        num_runs=num_runs,
        eval_stt_provider=data.eval_stt_provider,
        eval_stt_model=data.eval_stt_model,
    )
    db.add(comparison)
    db.flush()

    _build_benchmark_side_samples(
        comparison=comparison,
        side_label="A",
        cfg=side_a_cfg,
        sample_texts=data.sample_texts,
        num_runs=num_runs,
        organization_id=organization_id,
        db=db,
    )
    if side_b_cfg is not None:
        _build_benchmark_side_samples(
            comparison=comparison,
            side_label="B",
            cfg=side_b_cfg,
            sample_texts=data.sample_texts,
            num_runs=num_runs,
            organization_id=organization_id,
            db=db,
        )

    db.commit()
    db.refresh(comparison)
    return _serialize_comparison(comparison, db)


def _build_benchmark_name(
    side_a: BenchmarkSideConfig, side_b: Optional[BenchmarkSideConfig]
) -> str:
    def _label(side: BenchmarkSideConfig) -> str:
        if side.source_type == "tts":
            return (side.provider or "tts").strip() or "tts"
        return side.source_type.capitalize()

    a = _label(side_a)
    if side_b is None:
        return f"{a} benchmark"
    return f"{a} vs {_label(side_b)}"


@router.get("/comparisons", operation_id="listTTSComparisons")
async def list_comparisons(
    skip: int = 0,
    limit: int = 50,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    comparisons = (
        db.query(TTSComparison)
        .filter(TTSComparison.organization_id == organization_id)
        .order_by(TTSComparison.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    comparison_ids = [c.id for c in comparisons]
    shares_by_comparison: Dict[Any, TTSBlindTestShare] = {}
    response_counts_by_share: Dict[Any, int] = {}
    if comparison_ids:
        shares = (
            db.query(TTSBlindTestShare)
            .filter(TTSBlindTestShare.comparison_id.in_(comparison_ids))
            .all()
        )
        shares_by_comparison = {s.comparison_id: s for s in shares}
        if shares:
            from sqlalchemy import func as _func
            counts = (
                db.query(
                    TTSBlindTestResponse.share_id,
                    _func.count(TTSBlindTestResponse.id),
                )
                .filter(TTSBlindTestResponse.share_id.in_([s.id for s in shares]))
                .group_by(TTSBlindTestResponse.share_id)
                .all()
            )
            response_counts_by_share = {sid: int(cnt) for sid, cnt in counts}

    return [
        _serialize_comparison_summary(
            c,
            share=shares_by_comparison.get(c.id),
            response_count=response_counts_by_share.get(
                shares_by_comparison.get(c.id).id, 0
            ) if shares_by_comparison.get(c.id) else 0,
        )
        for c in comparisons
    ]


@router.get("/comparisons/{comparison_id}", operation_id="getTTSComparison")
async def get_comparison(
    comparison_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    comparison = _get_comparison_or_404(comparison_id, organization_id, db)
    return _serialize_comparison(comparison, db)


@router.post("/comparisons/{comparison_id}/generate", operation_id="generateTTSComparison")
async def generate_comparison(
    comparison_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Dispatch Celery task to generate TTS audio for all samples.

    For blind_test_only comparisons there's nothing to synthesize: all samples
    are pre-resolved to existing recordings/uploads/past TTS samples and were
    marked COMPLETED at create time, so we no-op here.
    """
    comparison = _get_comparison_or_404(comparison_id, organization_id, db)

    if (comparison.mode or "benchmark") == "blind_test_only":
        if comparison.status not in (
            TTSComparisonStatus.COMPLETED.value,
            TTSComparisonStatus.EVALUATING.value,
        ):
            comparison.status = TTSComparisonStatus.COMPLETED.value
            db.commit()
        return {"message": "Blind-test-only comparison is ready", "task_id": None}

    # If every sample is non-tts (e.g. recording vs recording benchmark) there
    # is nothing for the worker to do – mark completed and return.
    pending_tts_samples = (
        db.query(TTSSample)
        .filter(
            TTSSample.comparison_id == comparison.id,
            TTSSample.source_type == "tts",
            TTSSample.status == TTSSampleStatus.PENDING.value,
        )
        .count()
    )
    if pending_tts_samples == 0:
        comparison.status = TTSComparisonStatus.EVALUATING.value
        db.commit()
        try:
            from app.workers.celery_app import evaluate_tts_comparison_task
            evaluate_tts_comparison_task.delay(str(comparison.id))
        except Exception as e:
            logger.warning(
                f"[VoicePlayground] Failed to dispatch evaluation for non-TTS comparison: {e}"
            )
        return {"message": "No TTS samples to generate", "task_id": None}

    if comparison.status not in (
        TTSComparisonStatus.PENDING.value,
        TTSComparisonStatus.FAILED.value,
    ):
        raise HTTPException(400, f"Comparison is already in status '{comparison.status}'")

    comparison.status = TTSComparisonStatus.GENERATING.value
    db.commit()

    try:
        from app.workers.celery_app import generate_tts_comparison_task

        task = generate_tts_comparison_task.delay(str(comparison.id))
        comparison.celery_task_id = task.id
        db.commit()
        logger.info(f"[VoicePlayground] Dispatched generation task {task.id} for comparison {comparison.id}")
    except Exception as e:
        comparison.status = TTSComparisonStatus.FAILED.value
        comparison.error_message = str(e)
        db.commit()
        raise HTTPException(500, f"Failed to dispatch generation task: {e}")

    return {"message": "Generation started", "task_id": task.id}


@router.post("/comparisons/{comparison_id}/blind-test", operation_id="submitBlindTest")
async def submit_blind_test(
    comparison_id: UUID,
    data: BlindTestSubmit,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    comparison = _get_comparison_or_404(comparison_id, organization_id, db)
    comparison.blind_test_results = data.results
    db.commit()

    # Recalculate evaluation summary with blind test counts
    _recompute_summary(comparison, db)
    return {"message": "Blind test results saved"}


# ----------------------------------------------------------------------
# Blind Test Sharing (owner-side; gated by enterprise feature)
# ----------------------------------------------------------------------


@router.post("/comparisons/{comparison_id}/share", operation_id="createBlindTestShare")
async def create_blind_test_share(
    comparison_id: UUID,
    data: BlindTestShareCreate,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Create (or replace) a public blind test share for a comparison."""
    import secrets

    comparison = _get_comparison_or_404(comparison_id, organization_id, db)

    # Audio generation must be done; evaluation can still be running in the background.
    audio_ready_states = {
        TTSComparisonStatus.EVALUATING.value,
        TTSComparisonStatus.COMPLETED.value,
    }
    if comparison.status not in audio_ready_states:
        raise HTTPException(400, "Audio must finish generating before creating a blind test")

    # Blind tests need two playable sides. For benchmark mode that means
    # provider_b must be set (or side B contains non-tts samples). For
    # blind_test_only mode the create endpoint has already enforced this.
    has_b_samples = (
        db.query(TTSSample)
        .filter(
            TTSSample.comparison_id == comparison.id,
            TTSSample.side == "B",
            TTSSample.audio_s3_key.isnot(None),
        )
        .count()
    ) > 0
    if not has_b_samples:
        raise HTTPException(400, "Blind tests require a second side (B) with playable audio")

    metrics = _validate_custom_metrics([m.model_dump() for m in data.custom_metrics])
    title = (data.title or "").strip()
    if not title:
        raise HTTPException(400, "Share title is required")

    existing = db.query(TTSBlindTestShare).filter(
        TTSBlindTestShare.comparison_id == comparison.id,
    ).first()

    if existing:
        existing.title = title
        existing.description = data.description
        existing.custom_metrics = metrics
        existing.status = TTSBlindTestShareStatus.OPEN.value
        existing.closed_at = None
        share = existing
    else:
        share = TTSBlindTestShare(
            comparison_id=comparison.id,
            organization_id=organization_id,
            share_token=secrets.token_urlsafe(16),
            title=title,
            description=data.description,
            custom_metrics=metrics,
            status=TTSBlindTestShareStatus.OPEN.value,
            created_by=api_key or None,
        )
        db.add(share)

    db.commit()
    db.refresh(share)

    _recompute_summary(comparison, db)
    return _serialize_share(share, db, include_aggregates=True)


@router.get("/comparisons/{comparison_id}/share", operation_id="getBlindTestShare")
async def get_blind_test_share(
    comparison_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Fetch the share for a comparison (or 404 if none yet)."""
    comparison = _get_comparison_or_404(comparison_id, organization_id, db)
    share = db.query(TTSBlindTestShare).filter(
        TTSBlindTestShare.comparison_id == comparison.id,
    ).first()
    if not share:
        raise HTTPException(404, "No blind test share for this comparison")
    return _serialize_share(share, db, include_aggregates=True)


@router.patch("/shares/{share_id}", operation_id="updateBlindTestShare")
async def update_blind_test_share(
    share_id: UUID,
    data: BlindTestSharePatch,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    share = _get_share_or_404(share_id, organization_id, db)

    if data.title is not None:
        title = data.title.strip()
        if not title:
            raise HTTPException(400, "Title cannot be empty")
        share.title = title

    if data.description is not None:
        share.description = data.description

    if data.custom_metrics is not None:
        existing_keys = {m.get("key") for m in (share.custom_metrics or []) if isinstance(m, dict)}
        new_metrics = _validate_custom_metrics([m.model_dump() for m in data.custom_metrics])
        new_keys = {m["key"] for m in new_metrics}
        # Allow adding/relabelling, but require all previously-used keys remain
        # so already-recorded responses remain interpretable.
        response_count = (
            db.query(TTSBlindTestResponse)
            .filter(TTSBlindTestResponse.share_id == share.id)
            .count()
        )
        if response_count > 0 and not existing_keys.issubset(new_keys):
            removed = sorted(existing_keys - new_keys)
            raise HTTPException(
                400,
                f"Cannot remove metrics with existing responses: {removed}",
            )
        share.custom_metrics = new_metrics

    if data.status is not None:
        if data.status not in (TTSBlindTestShareStatus.OPEN.value, TTSBlindTestShareStatus.CLOSED.value):
            raise HTTPException(400, "status must be 'open' or 'closed'")
        share.status = data.status
        if data.status == TTSBlindTestShareStatus.CLOSED.value:
            from datetime import datetime, timezone
            share.closed_at = datetime.now(timezone.utc)
        else:
            share.closed_at = None

    db.commit()
    db.refresh(share)
    return _serialize_share(share, db, include_aggregates=True)


@router.delete("/shares/{share_id}", operation_id="deleteBlindTestShare")
async def delete_blind_test_share(
    share_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    share = _get_share_or_404(share_id, organization_id, db)
    comparison_id = share.comparison_id
    db.delete(share)
    db.commit()

    comparison = db.query(TTSComparison).filter(TTSComparison.id == comparison_id).first()
    if comparison:
        _recompute_summary(comparison, db)
    return {"message": "Blind test share deleted"}


@router.get("/shares/{share_id}/responses", operation_id="listBlindTestResponses")
async def list_blind_test_responses(
    share_id: UUID,
    skip: int = 0,
    limit: int = 100,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    share = _get_share_or_404(share_id, organization_id, db)
    rows = (
        db.query(TTSBlindTestResponse)
        .filter(TTSBlindTestResponse.share_id == share.id)
        .order_by(TTSBlindTestResponse.submitted_at.desc())
        .offset(skip)
        .limit(min(limit, 500))
        .all()
    )
    return {
        "items": [_serialize_response(r) for r in rows],
        "total": db.query(TTSBlindTestResponse).filter(TTSBlindTestResponse.share_id == share.id).count(),
    }


@router.get("/comparisons/{comparison_id}/samples/{sample_id}", operation_id="getTTSSample")
async def get_sample(
    comparison_id: UUID,
    sample_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Get a single TTS sample with full metrics (useful for analytics / future reference)."""
    _get_comparison_or_404(comparison_id, organization_id, db)
    sample = db.query(TTSSample).filter(
        TTSSample.id == sample_id,
        TTSSample.comparison_id == comparison_id,
    ).first()
    if not sample:
        raise HTTPException(404, "TTS sample not found")

    audio_url = None
    if sample.audio_s3_key:
        try:
            audio_url = s3_service.generate_presigned_url_by_key(sample.audio_s3_key, expiration=3600)
        except Exception:
            pass

    return {
        "id": str(sample.id),
        "comparison_id": str(sample.comparison_id),
        "provider": sample.provider,
        "model": sample.model,
        "voice_id": sample.voice_id,
        "voice_name": sample.voice_name,
        "side": sample.side,
        "sample_index": sample.sample_index,
        "run_index": sample.run_index if sample.run_index is not None else 0,
        "text": sample.text,
        "audio_url": audio_url,
        "audio_s3_key": sample.audio_s3_key,
        "duration_seconds": sample.duration_seconds,
        "latency_ms": sample.latency_ms,
        "ttfb_ms": sample.ttfb_ms,
        "evaluation_metrics": sample.evaluation_metrics,
        "status": sample.status,
        "error_message": sample.error_message,
        "created_at": sample.created_at.isoformat() if sample.created_at else None,
    }


@router.delete("/comparisons/{comparison_id}", operation_id="deleteTTSComparison")
async def delete_comparison(
    comparison_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    comparison = _get_comparison_or_404(comparison_id, organization_id, db)
    db.delete(comparison)
    db.commit()
    return {"message": "Comparison deleted"}


@router.get("/analytics", operation_id="getTTSAnalytics")
async def get_tts_analytics(
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Aggregate TTS sample metrics across all comparisons, grouped by provider/model/voice."""
    from collections import defaultdict

    samples = (
        db.query(TTSSample)
        .filter(
            TTSSample.organization_id == organization_id,
            TTSSample.status == TTSSampleStatus.COMPLETED.value,
            TTSSample.evaluation_metrics.isnot(None),
        )
        .all()
    )

    groups: Dict[tuple, List[TTSSample]] = defaultdict(list)
    for s in samples:
        key = (s.provider, s.model, s.voice_id, s.voice_name or s.voice_id)
        groups[key].append(s)

    metrics_keys = {
        "MOS Score": "avg_mos",
        "Valence": "avg_valence",
        "Arousal": "avg_arousal",
        "Prosody Score": "avg_prosody",
        "WER": "avg_wer",
        "CER": "avg_cer",
    }

    result = []
    for (provider, model, voice_id, voice_name), group_samples in groups.items():
        row: Dict[str, Any] = {
            "provider": provider,
            "model": model,
            "voice_id": voice_id,
            "voice_name": voice_name,
            "sample_count": len(group_samples),
        }

        for metric_key, output_key in metrics_keys.items():
            values = [
                s.evaluation_metrics.get(metric_key)
                for s in group_samples
                if s.evaluation_metrics and s.evaluation_metrics.get(metric_key) is not None
            ]
            row[output_key] = round(sum(values) / len(values), 3) if values else None

        latencies = [s.latency_ms for s in group_samples if s.latency_ms is not None]
        row["avg_latency_ms"] = round(sum(latencies) / len(latencies), 1) if latencies else None

        ttfbs = [s.ttfb_ms for s in group_samples if s.ttfb_ms is not None]
        row["avg_ttfb_ms"] = round(sum(ttfbs) / len(ttfbs), 1) if ttfbs else None

        result.append(row)

    result.sort(key=lambda r: r.get("avg_mos") or 0, reverse=True)
    return result


@router.get("/report-threshold-defaults", operation_id="getVoicePlaygroundReportThresholdDefaults")
async def get_voice_playground_report_threshold_defaults(
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(404, "Organization not found")

    stored = _sanitize_zone_threshold_overrides(org.voice_playground_threshold_overrides)
    is_custom = bool(stored)
    return {
        "zone_threshold_overrides": stored if is_custom else DEFAULT_ZONE_THRESHOLD_OVERRIDES,
        "is_custom": is_custom,
    }


@router.put("/report-threshold-defaults", operation_id="updateVoicePlaygroundReportThresholdDefaults")
async def update_voice_playground_report_threshold_defaults(
    data: VoicePlaygroundThresholdDefaultsUpdate,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(404, "Organization not found")

    if data.reset_to_system_defaults:
        org.voice_playground_threshold_overrides = None
    else:
        sanitized = _sanitize_zone_threshold_overrides(data.zone_threshold_overrides or {})
        org.voice_playground_threshold_overrides = sanitized

    db.commit()
    db.refresh(org)

    stored = _sanitize_zone_threshold_overrides(org.voice_playground_threshold_overrides)
    is_custom = bool(stored)
    return {
        "zone_threshold_overrides": stored if is_custom else DEFAULT_ZONE_THRESHOLD_OVERRIDES,
        "is_custom": is_custom,
        "message": "Voice Playground threshold defaults updated",
    }


@router.get("/comparisons/{comparison_id}/report.pdf", operation_id="downloadTTSComparisonReport")
async def download_tts_comparison_report(
    comparison_id: UUID,
    include_unfinished_samples: bool = False,
    report_options: Optional[str] = None,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Generate and return a PDF benchmark report for a comparison."""
    comparison = _get_comparison_or_404(comparison_id, organization_id, db)

    sample_query = db.query(TTSSample).filter(TTSSample.comparison_id == comparison.id)
    if not include_unfinished_samples:
        sample_query = sample_query.filter(TTSSample.status == TTSSampleStatus.COMPLETED.value)

    samples = (
        sample_query
        .order_by(TTSSample.run_index, TTSSample.sample_index, TTSSample.provider, TTSSample.voice_id)
        .all()
    )
    if not samples:
        raise HTTPException(400, "No samples found to generate report")

    try:
        options_dict = _parse_report_options(report_options)
        options_dict = _merge_org_threshold_defaults(db, organization_id, options_dict)
        payload = voice_playground_report_service.build_payload(
            comparison,
            samples,
            report_options=options_dict,
        )
        pdf_bytes = voice_playground_report_service.render_pdf(payload)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to generate PDF report: {str(e)}")

    filename = f"voice-playground-report-{comparison.simulation_id or str(comparison.id)[:8]}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/comparisons/{comparison_id}/reports", operation_id="createTTSComparisonReportJob")
async def create_tts_comparison_report_job(
    comparison_id: UUID,
    data: Optional[TTSReportJobCreate] = None,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Queue asynchronous PDF report generation for a comparison."""
    comparison = _get_comparison_or_404(comparison_id, organization_id, db)

    report_job = TTSReportJob(
        organization_id=organization_id,
        comparison_id=comparison.id,
        status=TTSReportJobStatus.PENDING.value,
        format="pdf",
        created_by=api_key,
    )
    db.add(report_job)
    db.commit()
    db.refresh(report_job)

    try:
        from app.workers.celery_app import generate_tts_report_pdf_task

        options_dict = (
            data.report_options.model_dump(exclude_none=True)
            if (data and data.report_options is not None)
            else {}
        )
        options_dict = _merge_org_threshold_defaults(db, organization_id, options_dict)
        task = generate_tts_report_pdf_task.delay(str(report_job.id), options_dict)
        report_job.celery_task_id = task.id
        db.commit()
    except Exception as e:
        report_job.status = TTSReportJobStatus.FAILED.value
        report_job.error_message = f"Failed to queue report task: {str(e)}"
        db.commit()
        raise HTTPException(500, "Failed to queue report generation")

    return {
        "id": str(report_job.id),
        "comparison_id": str(comparison.id),
        "status": report_job.status,
        "format": report_job.format,
        "task_id": report_job.celery_task_id,
        "report_options": options_dict,
        "created_at": report_job.created_at.isoformat() if report_job.created_at else None,
    }


@router.get("/reports/{report_job_id}", operation_id="getTTSComparisonReportJob")
async def get_tts_comparison_report_job(
    report_job_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Get asynchronous report generation status and download URL."""
    report_job = (
        db.query(TTSReportJob)
        .filter(
            TTSReportJob.id == report_job_id,
            TTSReportJob.organization_id == organization_id,
        )
        .first()
    )
    if not report_job:
        raise HTTPException(404, "Report job not found")

    download_url = None
    if report_job.status == TTSReportJobStatus.COMPLETED.value and report_job.s3_key:
        try:
            download_url = s3_service.generate_presigned_url_by_key(report_job.s3_key, expiration=3600)
        except Exception:
            download_url = None

    return {
        "id": str(report_job.id),
        "comparison_id": str(report_job.comparison_id),
        "status": report_job.status,
        "format": report_job.format,
        "filename": report_job.filename,
        "error_message": report_job.error_message,
        "task_id": report_job.celery_task_id,
        "download_url": download_url,
        "created_at": report_job.created_at.isoformat() if report_job.created_at else None,
        "updated_at": report_job.updated_at.isoformat() if report_job.updated_at else None,
    }


# ======================================================================
# Helpers
# ======================================================================


def _sanitize_zone_threshold_overrides(raw: Any) -> Dict[str, Dict[str, float]]:
    if not isinstance(raw, dict):
        return {}

    allowed_metric_keys = set(DEFAULT_ZONE_THRESHOLD_OVERRIDES.keys())
    allowed_threshold_keys = {"good_min", "neutral_min", "good_max", "neutral_max"}
    sanitized: Dict[str, Dict[str, float]] = {}

    for metric_key, metric_values in raw.items():
        if metric_key not in allowed_metric_keys or not isinstance(metric_values, dict):
            continue
        bucket: Dict[str, float] = {}
        for threshold_key, raw_val in metric_values.items():
            if threshold_key not in allowed_threshold_keys:
                continue
            try:
                bucket[threshold_key] = float(raw_val)
            except (TypeError, ValueError):
                continue
        if bucket:
            sanitized[metric_key] = bucket
    return sanitized


def _merge_org_threshold_defaults(db: Session, organization_id: UUID, report_options: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(report_options or {})

    org = db.query(Organization).filter(Organization.id == organization_id).first()
    org_defaults = _sanitize_zone_threshold_overrides(
        org.voice_playground_threshold_overrides if org else None
    )
    base_thresholds = org_defaults or DEFAULT_ZONE_THRESHOLD_OVERRIDES

    incoming_overrides = _sanitize_zone_threshold_overrides(merged.get("zone_threshold_overrides"))
    merged_thresholds: Dict[str, Dict[str, float]] = {}
    for metric_key, default_values in base_thresholds.items():
        merged_thresholds[metric_key] = dict(default_values)
        if metric_key in incoming_overrides:
            merged_thresholds[metric_key].update(incoming_overrides[metric_key])
    for metric_key, override_values in incoming_overrides.items():
        if metric_key not in merged_thresholds:
            merged_thresholds[metric_key] = dict(override_values)

    merged["zone_threshold_overrides"] = merged_thresholds
    return merged


def _parse_report_options(report_options_raw: Optional[str]) -> Dict[str, Any]:
    if not report_options_raw:
        return {}
    try:
        parsed = json.loads(report_options_raw)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid report_options JSON")

    if not isinstance(parsed, dict):
        raise HTTPException(400, "report_options must be a JSON object")

    try:
        validated = TTSReportOptions(**parsed)
    except Exception as exc:
        raise HTTPException(400, f"Invalid report options: {str(exc)}")

    return validated.model_dump(exclude_none=True)


def _get_comparison_or_404(comparison_id: UUID, organization_id: UUID, db: Session) -> TTSComparison:
    c = db.query(TTSComparison).filter(
        TTSComparison.id == comparison_id,
        TTSComparison.organization_id == organization_id,
    ).first()
    if not c:
        raise HTTPException(404, "TTS comparison not found")
    return c


def _get_share_or_404(share_id: UUID, organization_id: UUID, db: Session) -> TTSBlindTestShare:
    s = db.query(TTSBlindTestShare).filter(
        TTSBlindTestShare.id == share_id,
        TTSBlindTestShare.organization_id == organization_id,
    ).first()
    if not s:
        raise HTTPException(404, "Blind test share not found")
    return s


def _validate_custom_metrics(raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sanitize and validate custom blind-test metrics. Returns canonical list."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise HTTPException(400, "custom_metrics must be a list")
    if len(raw) > 20:
        raise HTTPException(400, "custom_metrics is limited to 20 entries")

    seen_keys: set = set()
    out: List[Dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise HTTPException(400, "Each metric must be an object")
        key = str(entry.get("key", "")).strip()
        label = str(entry.get("label", "")).strip()
        mtype = str(entry.get("type", "")).strip().lower()
        if not key or not label:
            raise HTTPException(400, "Each metric needs a key and label")
        if not key.replace("_", "").isalnum():
            raise HTTPException(400, f"Metric key '{key}' must be alphanumeric/underscore")
        if key in seen_keys:
            raise HTTPException(400, f"Duplicate metric key '{key}'")
        seen_keys.add(key)
        if mtype not in ("rating", "comment"):
            raise HTTPException(400, f"Metric '{key}' has invalid type '{mtype}'")

        clean: Dict[str, Any] = {"key": key, "label": label, "type": mtype}
        if mtype == "rating":
            try:
                scale = int(entry.get("scale") or 5)
            except (TypeError, ValueError):
                raise HTTPException(400, f"Metric '{key}' has invalid scale")
            if scale < 2 or scale > 10:
                raise HTTPException(400, f"Metric '{key}' scale must be between 2 and 10")
            clean["scale"] = scale
        out.append(clean)
    return out


def _serialize_share(
    share: TTSBlindTestShare, db: Session, *, include_aggregates: bool = False
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "id": str(share.id),
        "comparison_id": str(share.comparison_id),
        "share_token": share.share_token,
        "public_path": f"/blind-test/{share.share_token}",
        "title": share.title,
        "description": share.description,
        "custom_metrics": share.custom_metrics or [],
        "status": share.status,
        "created_at": share.created_at.isoformat() if share.created_at else None,
        "updated_at": share.updated_at.isoformat() if share.updated_at else None,
        "closed_at": share.closed_at.isoformat() if share.closed_at else None,
    }
    if include_aggregates:
        payload["response_count"] = (
            db.query(TTSBlindTestResponse)
            .filter(TTSBlindTestResponse.share_id == share.id)
            .count()
        )
        payload["aggregates"] = _aggregate_external_responses(share, db)
    return payload


def _serialize_response(r: TTSBlindTestResponse) -> Dict[str, Any]:
    return {
        "id": str(r.id),
        "share_id": str(r.share_id),
        "rater_name": r.rater_name,
        "rater_email": r.rater_email,
        "responses": r.responses,
        "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
    }


def _aggregate_external_responses(
    share: TTSBlindTestShare, db: Session
) -> Dict[str, Any]:
    """Aggregate all external rater responses for a share.

    Output shape:
    {
      "response_count": int,
      "a_wins": int, "b_wins": int, "a_pct": float, "b_pct": float,
      "metrics": {
        "<metric_key>": {
          "label": str, "scale": int|None,
          "avg_a": float|None, "avg_b": float|None, "samples": int
        }, ...
      }
    }
    """
    rows = (
        db.query(TTSBlindTestResponse)
        .filter(TTSBlindTestResponse.share_id == share.id)
        .all()
    )

    a_wins = 0
    b_wins = 0
    rating_metrics: List[Dict[str, Any]] = [
        m for m in (share.custom_metrics or []) if isinstance(m, dict) and m.get("type") == "rating"
    ]
    sums_a = {m["key"]: 0.0 for m in rating_metrics}
    counts_a = {m["key"]: 0 for m in rating_metrics}
    sums_b = {m["key"]: 0.0 for m in rating_metrics}
    counts_b = {m["key"]: 0 for m in rating_metrics}

    for r in rows:
        entries = r.responses or []
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            preferred = str(entry.get("preferred", "")).upper()
            if preferred == "A":
                a_wins += 1
            elif preferred == "B":
                b_wins += 1

            ratings_a = entry.get("ratings_a") or {}
            ratings_b = entry.get("ratings_b") or {}
            for m in rating_metrics:
                key = m["key"]
                va = ratings_a.get(key)
                vb = ratings_b.get(key)
                if isinstance(va, (int, float)):
                    sums_a[key] += float(va)
                    counts_a[key] += 1
                if isinstance(vb, (int, float)):
                    sums_b[key] += float(vb)
                    counts_b[key] += 1

    total = a_wins + b_wins
    metrics_out: Dict[str, Any] = {}
    for m in rating_metrics:
        key = m["key"]
        avg_a = round(sums_a[key] / counts_a[key], 3) if counts_a[key] else None
        avg_b = round(sums_b[key] / counts_b[key], 3) if counts_b[key] else None
        metrics_out[key] = {
            "label": m.get("label"),
            "scale": m.get("scale"),
            "avg_a": avg_a,
            "avg_b": avg_b,
            "samples_a": counts_a[key],
            "samples_b": counts_b[key],
        }

    return {
        "response_count": len(rows),
        "a_wins": a_wins,
        "b_wins": b_wins,
        "a_pct": round(a_wins / total * 100, 1) if total else 0,
        "b_pct": round(b_wins / total * 100, 1) if total else 0,
        "metrics": metrics_out,
    }


def _serialize_comparison_summary(
    c: TTSComparison,
    share: Optional[TTSBlindTestShare] = None,
    response_count: int = 0,
) -> Dict[str, Any]:
    return {
        "id": str(c.id),
        "simulation_id": c.simulation_id,
        "name": c.name,
        "status": c.status,
        "mode": getattr(c, "mode", "benchmark") or "benchmark",
        "provider_a": c.provider_a,
        "model_a": c.model_a,
        "provider_b": c.provider_b,
        "model_b": c.model_b,
        "sample_count": len(c.sample_texts) if c.sample_texts else 0,
        "num_runs": c.num_runs or 1,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "has_share": share is not None,
        "share_token": share.share_token if share else None,
        "share_status": share.status if share else None,
        "share_title": share.title if share else None,
        "response_count": response_count,
    }


def _serialize_comparison(c: TTSComparison, db: Session) -> Dict[str, Any]:
    samples = (
        db.query(TTSSample)
        .filter(TTSSample.comparison_id == c.id)
        .order_by(TTSSample.run_index, TTSSample.sample_index, TTSSample.provider, TTSSample.voice_id)
        .all()
    )

    serialized_samples = []
    for s in samples:
        audio_url = None
        if s.audio_s3_key:
            try:
                presigned = s3_service.generate_presigned_url_by_key(s.audio_s3_key, expiration=3600)
                audio_url = presigned
            except Exception:
                pass

        serialized_samples.append({
            "id": str(s.id),
            "provider": s.provider,
            "model": s.model,
            "voice_id": s.voice_id,
            "voice_name": s.voice_name,
            "side": s.side,
            "sample_index": s.sample_index,
            "run_index": s.run_index if s.run_index is not None else 0,
            "text": s.text,
            "audio_url": audio_url,
            "audio_s3_key": s.audio_s3_key,
            "duration_seconds": s.duration_seconds,
            "latency_ms": s.latency_ms,
            "ttfb_ms": s.ttfb_ms,
            "evaluation_metrics": s.evaluation_metrics,
            "status": s.status,
            "error_message": s.error_message,
            "source_type": getattr(s, "source_type", "tts") or "tts",
            "source_ref_id": str(s.source_ref_id) if getattr(s, "source_ref_id", None) else None,
        })

    share = db.query(TTSBlindTestShare).filter(TTSBlindTestShare.comparison_id == c.id).first()
    share_info = (
        {
            "id": str(share.id),
            "share_token": share.share_token,
            "public_path": f"/blind-test/{share.share_token}",
            "title": share.title,
            "status": share.status,
        }
        if share
        else None
    )

    return {
        "id": str(c.id),
        "simulation_id": c.simulation_id,
        "name": c.name,
        "status": c.status,
        "mode": getattr(c, "mode", "benchmark") or "benchmark",
        "provider_a": c.provider_a,
        "model_a": c.model_a,
        "voices_a": c.voices_a,
        "provider_b": c.provider_b,
        "model_b": c.model_b,
        "voices_b": c.voices_b,
        "sample_texts": c.sample_texts,
        "num_runs": c.num_runs or 1,
        "blind_test_results": c.blind_test_results,
        "evaluation_summary": c.evaluation_summary,
        "blind_test_share": share_info,
        "eval_stt_provider": getattr(c, "eval_stt_provider", None),
        "eval_stt_model": getattr(c, "eval_stt_model", None),
        "error_message": c.error_message,
        "samples": serialized_samples,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def _recompute_summary(comparison: TTSComparison, db: Session):
    """Recompute aggregated evaluation summary from samples + blind test."""
    samples = (
        db.query(TTSSample)
        .filter(TTSSample.comparison_id == comparison.id, TTSSample.evaluation_metrics.isnot(None))
        .all()
    )

    summary: Dict[str, Any] = {"provider_a": {}, "provider_b": {}}
    metrics_keys = ["MOS Score", "Valence", "Arousal", "Prosody Score", "WER", "CER"]

    for side, side_label, provider_val in [("provider_a", "A", comparison.provider_a), ("provider_b", "B", comparison.provider_b)]:
        side_samples = [s for s in samples if s.side == side_label] if any(s.side for s in samples) else [s for s in samples if s.provider == provider_val]
        if not side_samples:
            continue
        for mk in metrics_keys:
            values = [s.evaluation_metrics.get(mk) for s in side_samples if s.evaluation_metrics and s.evaluation_metrics.get(mk) is not None]
            if values:
                summary[side][mk] = round(sum(values) / len(values), 3)

        latencies = [s.latency_ms for s in side_samples if s.latency_ms is not None]
        if latencies:
            summary[side]["avg_latency_ms"] = round(sum(latencies) / len(latencies), 1)

        ttfbs = [s.ttfb_ms for s in side_samples if s.ttfb_ms is not None]
        if ttfbs:
            summary[side]["avg_ttfb_ms"] = round(sum(ttfbs) / len(ttfbs), 1)

    # Blind test tallying (owner's in-app + external sharable form, merged)
    a_wins = 0
    b_wins = 0

    if comparison.blind_test_results:
        a_wins += sum(1 for r in comparison.blind_test_results if r.get("preferred") == "A")
        b_wins += sum(1 for r in comparison.blind_test_results if r.get("preferred") == "B")

    share = (
        db.query(TTSBlindTestShare)
        .filter(TTSBlindTestShare.comparison_id == comparison.id)
        .first()
    )
    external_block: Optional[Dict[str, Any]] = None
    if share is not None:
        ext = _aggregate_external_responses(share, db)
        a_wins += ext["a_wins"]
        b_wins += ext["b_wins"]
        external_block = {
            "share_id": str(share.id),
            "share_token": share.share_token,
            "status": share.status,
            **ext,
        }

    if comparison.blind_test_results or external_block:
        total = a_wins + b_wins
        summary["blind_test"] = {
            "a_wins": a_wins,
            "b_wins": b_wins,
            "a_pct": round(a_wins / total * 100, 1) if total else 0,
            "b_pct": round(b_wins / total * 100, 1) if total else 0,
        }
        if external_block is not None:
            summary["blind_test"]["external"] = external_block

    comparison.evaluation_summary = summary
    db.commit()
