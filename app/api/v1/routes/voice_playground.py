"""
Voice Playground API Routes
TTS A/B comparison: generate audio, blind test, and quality evaluation.
"""

import random

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Dict, Any, List, Optional
from uuid import UUID
from pydantic import BaseModel
from loguru import logger

from app.dependencies import get_db, get_organization_id, get_api_key
from app.models.database import (
    AIProvider,
    Integration,
    TTSComparison,
    TTSSample,
    TTSComparisonStatus,
    TTSSampleStatus,
    ModelProvider,
    VoiceBundle,
)
from app.services.model_config_service import model_config_service
from app.services.s3_service import s3_service
from app.services.llm_service import llm_service

router = APIRouter(prefix="/voice-playground", tags=["Voice Playground"])


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
}

PROVIDERS_WITH_TTS = {"openai", "elevenlabs", "cartesia", "deepgram", "google"}

# ======================================================================
# Schemas
# ======================================================================


class TTSComparisonCreate(BaseModel):
    name: Optional[str] = None
    provider_a: str
    model_a: str
    voices_a: List[Dict[str, str]]  # [{"id": "...", "name": "..."}]
    provider_b: str
    model_b: str
    voices_b: List[Dict[str, str]]
    sample_texts: List[str]
    num_runs: int = 1


class BlindTestSubmit(BaseModel):
    results: List[Dict[str, Any]]
    # Each entry: {"sample_index": 0, "preferred": "A" | "B", "voice_a_id": "...", "voice_b_id": "..."}


class GenerateSamplesRequest(BaseModel):
    voice_bundle_id: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    scenario: Optional[str] = None
    count: int = 5
    temperature: Optional[float] = 0.8


SAMPLE_GENERATION_SYSTEM_PROMPT = """You are an expert at creating realistic text-to-speech sample scripts. \
Generate short, natural-sounding sentences that would be spoken aloud by a voice AI agent. \
Each sample should be 1-3 sentences, varied in tone and content, and suitable for evaluating TTS voice quality. \
Include a mix of: greetings, questions, informational statements, numbers/dates, and emotional expressions. \
Return ONLY a JSON array of strings, with no additional text or markdown formatting."""


# ======================================================================
# Endpoints
# ======================================================================


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
    scenario_text = data.scenario or "general customer service and voice assistant interactions"
    user_prompt = (
        f"Generate exactly {count} TTS sample texts for the following scenario:\n"
        f"Scenario: {scenario_text}\n\n"
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
            max_tokens=1500,
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


@router.get("/tts-providers", operation_id="listTTSProviders")
async def list_tts_providers(
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """List TTS providers that have an active API key configured."""
    # Gather active AI providers
    ai_providers = db.query(AIProvider).filter(
        AIProvider.organization_id == organization_id,
        AIProvider.is_active == True,
    ).all()

    active_provider_keys = set()
    for ap in ai_providers:
        pval = ap.provider.lower() if ap.provider else ""
        if pval in PROVIDERS_WITH_TTS:
            active_provider_keys.add(pval)

    # Also check Integration table for cartesia / elevenlabs / deepgram
    integrations = db.query(Integration).filter(
        Integration.organization_id == organization_id,
        Integration.is_active == True,
    ).all()
    for integ in integrations:
        pval = integ.platform.lower() if integ.platform else ""
        if pval in PROVIDERS_WITH_TTS:
            active_provider_keys.add(pval)

    result = []
    for provider_key in sorted(active_provider_keys):
        # Get TTS models from models.json
        try:
            provider_enum = ModelProvider(provider_key)
            tts_models = model_config_service.get_models_by_type(provider_enum, "tts")
        except (ValueError, Exception):
            tts_models = []

        if not tts_models:
            continue

        voices = TTS_VOICES.get(provider_key, [])

        result.append({
            "provider": provider_key,
            "models": tts_models,
            "voices": voices,
        })

    return result


@router.post("/comparisons", operation_id="createTTSComparison")
async def create_comparison(
    data: TTSComparisonCreate,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Create a new TTS comparison session and its sample records."""
    if not data.sample_texts:
        raise HTTPException(400, "At least one sample text is required")
    if not data.voices_a or not data.voices_b:
        raise HTTPException(400, "At least one voice per provider is required")

    num_runs = max(1, min(data.num_runs, 10))

    simulation_id = _generate_unique_simulation_id(db)

    comparison = TTSComparison(
        organization_id=organization_id,
        simulation_id=simulation_id,
        name=data.name or f"{data.provider_a} vs {data.provider_b}",
        status=TTSComparisonStatus.PENDING.value,
        provider_a=data.provider_a,
        model_a=data.model_a,
        voices_a=[v if isinstance(v, dict) else {"id": v} for v in data.voices_a],
        provider_b=data.provider_b,
        model_b=data.model_b,
        voices_b=[v if isinstance(v, dict) else {"id": v} for v in data.voices_b],
        sample_texts=data.sample_texts,
        num_runs=num_runs,
    )
    db.add(comparison)
    db.flush()

    for run in range(num_runs):
        for idx, text in enumerate(data.sample_texts):
            for voice in data.voices_a:
                vid = voice["id"] if isinstance(voice, dict) else voice
                vname = voice.get("name", vid) if isinstance(voice, dict) else vid
                db.add(TTSSample(
                    comparison_id=comparison.id,
                    organization_id=organization_id,
                    provider=data.provider_a,
                    model=data.model_a,
                    voice_id=vid,
                    voice_name=vname,
                    sample_index=idx,
                    run_index=run,
                    text=text,
                    status=TTSSampleStatus.PENDING.value,
                ))

            for voice in data.voices_b:
                vid = voice["id"] if isinstance(voice, dict) else voice
                vname = voice.get("name", vid) if isinstance(voice, dict) else vid
                db.add(TTSSample(
                    comparison_id=comparison.id,
                    organization_id=organization_id,
                    provider=data.provider_b,
                    model=data.model_b,
                    voice_id=vid,
                    voice_name=vname,
                    sample_index=idx,
                    run_index=run,
                    text=text,
                    status=TTSSampleStatus.PENDING.value,
                ))

    db.commit()
    db.refresh(comparison)
    return _serialize_comparison(comparison, db)


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
    return [_serialize_comparison_summary(c) for c in comparisons]


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
    """Dispatch Celery task to generate TTS audio for all samples."""
    comparison = _get_comparison_or_404(comparison_id, organization_id, db)

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
        "sample_index": sample.sample_index,
        "run_index": sample.run_index if sample.run_index is not None else 0,
        "text": sample.text,
        "audio_url": audio_url,
        "audio_s3_key": sample.audio_s3_key,
        "duration_seconds": sample.duration_seconds,
        "latency_ms": sample.latency_ms,
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

        result.append(row)

    result.sort(key=lambda r: r.get("avg_mos") or 0, reverse=True)
    return result


# ======================================================================
# Helpers
# ======================================================================


def _get_comparison_or_404(comparison_id: UUID, organization_id: UUID, db: Session) -> TTSComparison:
    c = db.query(TTSComparison).filter(
        TTSComparison.id == comparison_id,
        TTSComparison.organization_id == organization_id,
    ).first()
    if not c:
        raise HTTPException(404, "TTS comparison not found")
    return c


def _serialize_comparison_summary(c: TTSComparison) -> Dict[str, Any]:
    return {
        "id": str(c.id),
        "simulation_id": c.simulation_id,
        "name": c.name,
        "status": c.status,
        "provider_a": c.provider_a,
        "model_a": c.model_a,
        "provider_b": c.provider_b,
        "model_b": c.model_b,
        "sample_count": len(c.sample_texts) if c.sample_texts else 0,
        "num_runs": c.num_runs or 1,
        "created_at": c.created_at.isoformat() if c.created_at else None,
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
            "sample_index": s.sample_index,
            "run_index": s.run_index if s.run_index is not None else 0,
            "text": s.text,
            "audio_url": audio_url,
            "audio_s3_key": s.audio_s3_key,
            "duration_seconds": s.duration_seconds,
            "latency_ms": s.latency_ms,
            "evaluation_metrics": s.evaluation_metrics,
            "status": s.status,
            "error_message": s.error_message,
        })

    return {
        "id": str(c.id),
        "simulation_id": c.simulation_id,
        "name": c.name,
        "status": c.status,
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
    metrics_keys = ["MOS Score", "Valence", "Arousal", "Prosody Score"]

    for side, provider_val in [("provider_a", comparison.provider_a), ("provider_b", comparison.provider_b)]:
        side_samples = [s for s in samples if s.provider == provider_val]
        if not side_samples:
            continue
        for mk in metrics_keys:
            values = [s.evaluation_metrics.get(mk) for s in side_samples if s.evaluation_metrics and s.evaluation_metrics.get(mk) is not None]
            if values:
                summary[side][mk] = round(sum(values) / len(values), 3)

        latencies = [s.latency_ms for s in side_samples if s.latency_ms is not None]
        if latencies:
            summary[side]["avg_latency_ms"] = round(sum(latencies) / len(latencies), 1)

    # Blind test tallying
    if comparison.blind_test_results:
        a_wins = sum(1 for r in comparison.blind_test_results if r.get("preferred") == "A")
        b_wins = sum(1 for r in comparison.blind_test_results if r.get("preferred") == "B")
        total = a_wins + b_wins
        summary["blind_test"] = {
            "a_wins": a_wins,
            "b_wins": b_wins,
            "a_pct": round(a_wins / total * 100, 1) if total else 0,
            "b_pct": round(b_wins / total * 100, 1) if total else 0,
        }

    comparison.evaluation_summary = summary
    db.commit()
