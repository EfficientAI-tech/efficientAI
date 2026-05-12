"""Metrics routes."""

import json
import re
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import and_
from uuid import UUID
from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field
from loguru import logger

from app.database import get_db
from app.dependencies import get_organization_id, get_api_key
from app.models.database import Metric, MetricType, MetricTrigger, ModelProvider
from app.models.schemas import (
    MetricCreate,
    MetricUpdate,
    MetricResponse,
)

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.post("", response_model=MetricResponse, status_code=201)
def create_metric(
    metric_data: MetricCreate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Create a new metric."""
    # Check if metric with same name already exists for this organization
    existing = db.query(Metric).filter(
        and_(
            Metric.name == metric_data.name,
            Metric.organization_id == organization_id
        )
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A metric with this name already exists"
        )

    enabled_surfaces = (
        metric_data.enabled_surfaces
        if metric_data.enabled_surfaces is not None
        else ((metric_data.supported_surfaces or ["agent"]) if metric_data.enabled else [])
    )
    metric = Metric(
        organization_id=organization_id,
        name=metric_data.name,
        description=metric_data.description,
        metric_type=metric_data.metric_type,
        trigger=metric_data.trigger,
        enabled=len(enabled_surfaces) > 0,
        is_default=False,
        metric_origin=metric_data.metric_origin or "custom",
        supported_surfaces=metric_data.supported_surfaces or ["agent"],
        enabled_surfaces=enabled_surfaces,
        custom_data_type=metric_data.custom_data_type,
        custom_config=metric_data.custom_config,
        tags=metric_data.tags,
    )
    db.add(metric)
    db.commit()
    db.refresh(metric)

    return metric


@router.get("", response_model=List[MetricResponse])
def list_metrics(
    surface: Optional[str] = None,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """List all metrics for the organization."""
    query = db.query(Metric).filter(
        Metric.organization_id == organization_id,
        ~Metric.name.in_(REMOVED_DEFAULT_METRICS),
    )
    metrics = query.order_by(Metric.is_default.desc(), Metric.created_at.desc()).all()
    if surface:
        normalized_surface = surface.strip().lower()
        metrics = [
            m for m in metrics
            if normalized_surface in (m.supported_surfaces or [])
        ]
    return metrics


@router.get("/{metric_id}", response_model=MetricResponse)
def get_metric(
    metric_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Get a specific metric."""
    metric = db.query(Metric).filter(
        and_(
            Metric.id == metric_id,
            Metric.organization_id == organization_id
        )
    ).first()

    if not metric:
        raise HTTPException(status_code=404, detail="Metric not found")

    return metric


@router.put("/{metric_id}", response_model=MetricResponse)
def update_metric(
    metric_id: UUID,
    metric_data: MetricUpdate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Update a metric."""
    metric = db.query(Metric).filter(
        and_(
            Metric.id == metric_id,
            Metric.organization_id == organization_id
        )
    ).first()

    if not metric:
        raise HTTPException(status_code=404, detail="Metric not found")

    # Don't allow updating default metrics' core properties
    if metric.is_default:
        if metric_data.name is not None and metric_data.name != metric.name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot rename default metrics"
            )
        if metric_data.metric_type is not None and metric_data.metric_type != metric.metric_type:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot change metric type of default metrics"
            )

    # Update fields if provided
    if metric_data.name is not None:
        # Check for name conflicts
        existing = db.query(Metric).filter(
            and_(
                Metric.name == metric_data.name,
                Metric.organization_id == organization_id,
                Metric.id != metric_id
            )
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A metric with this name already exists"
            )
        metric.name = metric_data.name

    if metric_data.description is not None:
        metric.description = metric_data.description

    if metric_data.metric_type is not None:
        metric.metric_type = metric_data.metric_type

    if metric_data.trigger is not None:
        metric.trigger = metric_data.trigger

    if metric_data.enabled is not None:
        metric.enabled = metric_data.enabled
        if metric_data.enabled and not metric.enabled_surfaces:
            metric.enabled_surfaces = metric.supported_surfaces or ["agent"]
        elif not metric_data.enabled:
            metric.enabled_surfaces = []

    if metric_data.metric_origin is not None:
        metric.metric_origin = metric_data.metric_origin

    if metric_data.supported_surfaces is not None:
        metric.supported_surfaces = metric_data.supported_surfaces
        if metric.enabled and not metric_data.enabled_surfaces:
            metric.enabled_surfaces = metric_data.supported_surfaces

    if metric_data.enabled_surfaces is not None:
        metric.enabled_surfaces = metric_data.enabled_surfaces
        metric.enabled = len(metric_data.enabled_surfaces) > 0

    if metric_data.custom_data_type is not None:
        metric.custom_data_type = metric_data.custom_data_type

    if metric_data.custom_config is not None:
        metric.custom_config = metric_data.custom_config

    if metric_data.tags is not None:
        metric.tags = metric_data.tags

    db.commit()
    db.refresh(metric)

    return metric


# Deprecated default metrics that can be deleted
DEPRECATED_DEFAULT_METRICS = {"Response Time", "Customer Satisfaction", "Clarity and Empathy"}
# Removed default metrics should no longer be listed/seeded/evaluated.
REMOVED_DEFAULT_METRICS = {"Clarity and Empathy"}


@router.delete("/{metric_id}", status_code=204)
def delete_metric(
    metric_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Delete a metric."""
    metric = db.query(Metric).filter(
        and_(
            Metric.id == metric_id,
            Metric.organization_id == organization_id
        )
    ).first()

    if not metric:
        raise HTTPException(status_code=404, detail="Metric not found")

    # Allow deletion of deprecated default metrics
    if metric.is_default and metric.name not in DEPRECATED_DEFAULT_METRICS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete default metrics"
        )

    db.delete(metric)
    db.commit()

    return None


@router.post("/seed-defaults", response_model=List[MetricResponse], status_code=201)
def seed_default_metrics(
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Seed default metrics for an organization."""
    default_metrics = [
        # =========================================================================
        # LLM-Evaluated Metrics (Subjective assessments from conversation text)
        # =========================================================================
        {
            "name": "Follow Instructions",
            "description": "Measures how well the agent follows instructions and guidelines",
            "metric_type": MetricType.RATING,
            "trigger": MetricTrigger.ALWAYS,
            "enabled": True,
            "metric_origin": "default",
            "supported_surfaces": ["agent", "voice_playground"],
            "enabled_surfaces": ["agent", "voice_playground"],
        },
        {
            "name": "Professionalism",
            "description": "Assesses the professional tone and behavior throughout the conversation",
            "metric_type": MetricType.RATING,
            "trigger": MetricTrigger.ALWAYS,
            "enabled": True,
            "metric_origin": "default",
            "supported_surfaces": ["agent"],
            "enabled_surfaces": ["agent"],
        },
        {
            "name": "Problem Resolution",
            "description": "Measures the effectiveness in resolving customer issues",
            "metric_type": MetricType.BOOLEAN,
            "trigger": MetricTrigger.ALWAYS,
            "enabled": True,
            "metric_origin": "default",
            "supported_surfaces": ["agent"],
            "enabled_surfaces": ["agent"],
        },
        # =========================================================================
        # Acoustic Metrics (Parselmouth - traditional voice analysis)
        # =========================================================================
        {
            "name": "Pitch Variance",
            "description": "Measures F0 (fundamental frequency) variation in Hz - indicates prosodic expressiveness. Higher values suggest more expressive speech.",
            "metric_type": MetricType.NUMBER,
            "trigger": MetricTrigger.ALWAYS,
            "enabled": True,
            "metric_origin": "default",
            "supported_surfaces": ["voice_playground"],
            "enabled_surfaces": ["voice_playground"],
        },
        {
            "name": "Jitter",
            "description": "Cycle-to-cycle pitch period variation as percentage - indicates vocal stability. Lower values (< 1%) indicate stable voice.",
            "metric_type": MetricType.NUMBER,
            "trigger": MetricTrigger.ALWAYS,
            "enabled": False,
            "metric_origin": "default",
            "supported_surfaces": ["voice_playground"],
            "enabled_surfaces": [],
        },
        {
            "name": "Shimmer",
            "description": "Cycle-to-cycle amplitude variation as percentage - indicates voice quality. Lower values (< 3%) indicate consistent voice.",
            "metric_type": MetricType.NUMBER,
            "trigger": MetricTrigger.ALWAYS,
            "enabled": False,
            "metric_origin": "default",
            "supported_surfaces": ["voice_playground"],
            "enabled_surfaces": [],
        },
        {
            "name": "HNR",
            "description": "Harmonics-to-Noise Ratio in dB - indicates voice clarity. Higher values (> 20 dB) indicate cleaner voice with less breathiness.",
            "metric_type": MetricType.NUMBER,
            "trigger": MetricTrigger.ALWAYS,
            "enabled": False,
            "metric_origin": "default",
            "supported_surfaces": ["voice_playground"],
            "enabled_surfaces": [],
        },
        # =========================================================================
        # AI Voice Metrics (ML models - human-likeness, emotion, consistency)
        # =========================================================================
        {
            "name": "MOS Score",
            "description": "Mean Opinion Score (1.0-5.0) - predicts human perception of audio quality. 1-2: Poor/robotic, 3: Telephone quality, 4-5: Studio/high fidelity.",
            "metric_type": MetricType.NUMBER,
            "trigger": MetricTrigger.ALWAYS,
            "enabled": True,
            "metric_origin": "default",
            "supported_surfaces": ["voice_playground"],
            "enabled_surfaces": ["voice_playground"],
        },
        {
            "name": "Emotion Category",
            "description": "Categorical emotion detected in the voice (angry, happy, sad, neutral, fearful, disgusted, surprised).",
            "metric_type": MetricType.RATING,  # Stored as text category
            "trigger": MetricTrigger.ALWAYS,
            "enabled": True,
            "metric_origin": "default",
            "supported_surfaces": ["voice_playground"],
            "enabled_surfaces": ["voice_playground"],
        },
        {
            "name": "Emotion Confidence",
            "description": "Confidence score (0.0-1.0) for the detected emotion category.",
            "metric_type": MetricType.NUMBER,
            "trigger": MetricTrigger.ALWAYS,
            "enabled": True,
            "metric_origin": "default",
            "supported_surfaces": ["voice_playground"],
            "enabled_surfaces": ["voice_playground"],
        },
        {
            "name": "Valence",
            "description": "Emotional positivity/negativity (-1.0 to +1.0). Negative = sad/angry, Positive = happy/excited.",
            "metric_type": MetricType.NUMBER,
            "trigger": MetricTrigger.ALWAYS,
            "enabled": True,
            "metric_origin": "default",
            "supported_surfaces": ["voice_playground"],
            "enabled_surfaces": ["voice_playground"],
        },
        {
            "name": "Arousal",
            "description": "Emotional intensity/energy (0.0-1.0). Low = calm/sleepy, High = excited/energetic.",
            "metric_type": MetricType.NUMBER,
            "trigger": MetricTrigger.ALWAYS,
            "enabled": True,
            "metric_origin": "default",
            "supported_surfaces": ["voice_playground"],
            "enabled_surfaces": ["voice_playground"],
        },
        {
            "name": "Speaker Consistency",
            "description": "Voice identity stability (0.0-1.0). Compares start vs end of call. >0.8 = same voice, <0.5 = voice change detected (possible glitch).",
            "metric_type": MetricType.NUMBER,
            "trigger": MetricTrigger.ALWAYS,
            "enabled": True,
            "metric_origin": "default",
            "supported_surfaces": ["voice_playground"],
            "enabled_surfaces": ["voice_playground"],
        },
        {
            "name": "Prosody Score",
            "description": "Expressiveness/Drama score (0.0-1.0). Low = monotone/flat, High = expressive/dynamic storyteller.",
            "metric_type": MetricType.NUMBER,
            "trigger": MetricTrigger.ALWAYS,
            "enabled": True,
            "metric_origin": "default",
            "supported_surfaces": ["voice_playground"],
            "enabled_surfaces": ["voice_playground"],
        },
    ]

    # Names of default voice metrics that must always be enabled on the
    # voice_playground surface for existing organizations. These are the
    # qualitative audio metrics computed by qualitative_voice_service that
    # the voice playground relies on; the worker honors enabled_surfaces and
    # will skip computation entirely if none are enabled.
    voice_playground_required_defaults = {
        "MOS Score", "Valence", "Arousal", "Prosody Score",
        "Emotion Category", "Emotion Confidence", "Speaker Consistency",
    }

    created_metrics = []
    for metric_data in default_metrics:
        # Check if metric already exists
        existing = db.query(Metric).filter(
            and_(
                Metric.name == metric_data["name"],
                Metric.organization_id == organization_id
            )
        ).first()

        if not existing:
            metric = Metric(
                organization_id=organization_id,
                name=metric_data["name"],
                description=metric_data["description"],
                metric_type=metric_data["metric_type"],
                trigger=metric_data["trigger"],
                enabled=metric_data["enabled"],
                is_default=True,
                metric_origin=metric_data.get("metric_origin", "default"),
                supported_surfaces=metric_data.get("supported_surfaces", ["agent"]),
                enabled_surfaces=metric_data.get("enabled_surfaces", ["agent"]),
            )
            db.add(metric)
            created_metrics.append(metric)
        else:
            # Keep default acoustic metric toggles aligned with product defaults.
            if existing.enabled != metric_data["enabled"]:
                existing.enabled = metric_data["enabled"]
            # Re-assert voice_playground surface enrollment for the four required
            # voice metrics so existing orgs pick up the new default behavior.
            if metric_data["name"] in voice_playground_required_defaults:
                supported = list(existing.supported_surfaces or [])
                if "voice_playground" not in supported:
                    supported.append("voice_playground")
                    existing.supported_surfaces = supported
                enabled_surfaces = list(existing.enabled_surfaces or [])
                if "voice_playground" not in enabled_surfaces:
                    enabled_surfaces.append("voice_playground")
                    existing.enabled_surfaces = enabled_surfaces
                    existing.enabled = True

    # Ensure removed defaults are disabled for existing orgs.
    removed_metrics = db.query(Metric).filter(
        and_(
            Metric.organization_id == organization_id,
            Metric.name.in_(REMOVED_DEFAULT_METRICS),
            Metric.enabled == True,
        )
    ).all()
    for metric in removed_metrics:
        metric.enabled = False

    db.commit()
    for metric in created_metrics:
        db.refresh(metric)

    return created_metrics


# =============================================================================
# AI metric generation
# =============================================================================

class MetricGenerateExample(BaseModel):
    """One labeled example used to infer a metric definition."""
    transcript: str
    rating: Any  # number, boolean, or label (model-decided)
    notes: Optional[str] = None


class MetricGenerateRequest(BaseModel):
    """Request body for AI-generated metric suggestion."""
    mode: Literal["description", "examples"]
    surface: Literal["agent", "voice_playground", "blind_test"] = "agent"
    description: Optional[str] = Field(
        default=None,
        description="Free-form description of what the metric should measure (mode=description).",
    )
    examples: Optional[List[MetricGenerateExample]] = Field(
        default=None,
        description="Labeled examples used to infer the metric (mode=examples).",
    )


class MetricGenerateResponse(BaseModel):
    """Suggested (un-persisted) metric definition returned to the client."""
    name: str
    description: str
    metric_type: Literal["rating", "boolean", "number", "text"]
    custom_data_type: Optional[Literal["boolean", "enum", "number_range"]] = None
    custom_config: Dict[str, Any] = {}
    supported_surfaces: List[str]
    enabled_surfaces: List[str]
    suggested_tags: List[str] = []


def _build_metric_generation_messages(req: MetricGenerateRequest) -> List[Dict[str, str]]:
    """Build the LLM prompt for generating a metric definition."""
    surfaces_block = (
        f'  - "supported_surfaces": list, must include "{req.surface}". '
        f'Other allowed values: "agent", "voice_playground", "blind_test".\n'
        f'  - "enabled_surfaces": list, default to the same as supported_surfaces.\n'
    )

    schema_block = """
You MUST respond with ONLY a JSON object (no markdown, no commentary) with this exact shape:
{
  "name": str (concise, Title Case, <= 60 chars),
  "description": str (1-3 sentences explaining what is measured and how to score it),
  "metric_type": "rating" | "boolean" | "number" | "text",
  "custom_data_type": "boolean" | "enum" | "number_range" | null,
  "custom_config": {
      // for "enum": {"options": ["...", "..."]}
      // for "number_range": {"min": <number>, "max": <number>, "step": <number>}
      // for "boolean": {}
      // for "text": {}  (no extra config; the description tells the LLM what to summarize)
  },
  "supported_surfaces": ["agent" | "voice_playground" | "blind_test", ...],
  "enabled_surfaces": ["agent" | "voice_playground" | "blind_test", ...],
  "suggested_tags": ["...", "..."]
}

Rules:
  - "metric_type" must align with "custom_data_type":
      boolean -> "boolean", enum -> "rating", number_range -> "number".
  - Use "text" ONLY when the user clearly wants a free-form sentence /
    summary / explanation / classification label as the answer (e.g. "summarize
    the call", "extract the customer's main concern", "describe what went
    wrong in one paragraph"). For text metrics, set "custom_data_type" to null
    and "custom_config" to {}.
  - Otherwise prefer a structured numeric/boolean/enum metric.
""" + surfaces_block

    system_message = (
        "You are an expert evaluation designer. You translate a user's intent into a "
        "well-formed evaluation metric definition that can be judged by an LLM-as-judge. "
        "Always respond with valid JSON only."
    )

    if req.mode == "description":
        user_message = (
            "Generate a single evaluation metric definition based on the user's request below. "
            f'The metric will be evaluated on the "{req.surface}" surface.\n\n'
            f"## User intent\n{(req.description or '').strip()}\n"
            f"{schema_block}"
        )
    else:
        examples_text = "\n".join(
            f"- Example {i + 1}:\n  transcript: {ex.transcript!r}\n  rating: {ex.rating!r}"
            + (f"\n  notes: {ex.notes!r}" if ex.notes else "")
            for i, ex in enumerate(req.examples or [])
        )
        user_message = (
            "Infer a single evaluation metric definition that explains the rating pattern "
            f'in the labeled examples below. The metric will be evaluated on the "{req.surface}" '
            "surface.\n\n"
            f"## Labeled examples\n{examples_text}\n"
            f"{schema_block}"
        )

    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ]


def _parse_metric_generation_response(text: str) -> Dict[str, Any]:
    """Extract a JSON object from the LLM response text."""
    cleaned = text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned.replace("```json", "").replace("```", "").strip()
    elif cleaned.startswith("```"):
        cleaned = cleaned.replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if match:
            return json.loads(match.group())
        raise


@router.post("/generate", response_model=MetricGenerateResponse)
def generate_metric(
    req: MetricGenerateRequest,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Use an LLM to suggest a metric definition. Does NOT persist anything."""
    if req.mode == "description" and not (req.description and req.description.strip()):
        raise HTTPException(status_code=400, detail="description is required when mode='description'")
    if req.mode == "examples" and not (req.examples and len(req.examples) > 0):
        raise HTTPException(status_code=400, detail="At least one example is required when mode='examples'")

    from app.services.ai.llm_service import llm_service

    messages = _build_metric_generation_messages(req)

    try:
        llm_result = llm_service.generate_response(
            messages=messages,
            llm_provider=ModelProvider.OPENAI,
            llm_model="gpt-4o",
            organization_id=organization_id,
            db=db,
            temperature=0.4,
            max_tokens=800,
        )
    except Exception as e:
        logger.error(f"[Metric Generate] LLM call failed: {e}")
        raise HTTPException(status_code=502, detail=f"LLM call failed: {e}")

    try:
        parsed = _parse_metric_generation_response(llm_result.get("text", ""))
    except Exception as e:
        logger.error(f"[Metric Generate] Failed to parse LLM JSON: {e}")
        raise HTTPException(status_code=502, detail="Could not parse LLM response as JSON")

    allowed_surfaces = {"agent", "voice_playground", "blind_test"}
    supported = [s for s in (parsed.get("supported_surfaces") or []) if s in allowed_surfaces]
    if req.surface not in supported:
        supported = list({*supported, req.surface})
    enabled_surfaces = [s for s in (parsed.get("enabled_surfaces") or supported) if s in supported]
    if not enabled_surfaces:
        enabled_surfaces = list(supported)

    metric_type = (parsed.get("metric_type") or "rating").lower()
    if metric_type not in {"rating", "boolean", "number", "text"}:
        metric_type = "rating"

    custom_data_type = parsed.get("custom_data_type")
    if custom_data_type not in {"boolean", "enum", "number_range", None}:
        custom_data_type = None

    # Text metrics are unstructured by definition: no custom_data_type,
    # no extra config. Force-clear both regardless of what the LLM said so a
    # stale enum/number_range hint never sneaks through.
    if metric_type == "text":
        custom_data_type = None
        custom_config: Dict[str, Any] = {}
    else:
        if custom_data_type is None:
            custom_data_type = (
                "boolean" if metric_type == "boolean"
                else "number_range" if metric_type == "number"
                else "enum"
            )

        custom_config = parsed.get("custom_config") or {}
        if custom_data_type == "enum" and not isinstance(custom_config.get("options"), list):
            custom_config = {"options": ["Excellent", "Good", "Neutral", "Poor"]}
        if custom_data_type == "number_range":
            custom_config = {
                "min": float(custom_config.get("min", 0)),
                "max": float(custom_config.get("max", 10)),
                "step": float(custom_config.get("step", 1)),
            }
        if custom_data_type == "boolean":
            custom_config = {}

    name = (parsed.get("name") or "Custom Metric").strip()[:60]
    existing = db.query(Metric).filter(
        and_(Metric.name == name, Metric.organization_id == organization_id)
    ).first()
    if existing:
        suffix = 2
        while db.query(Metric).filter(
            and_(Metric.name == f"{name} ({suffix})", Metric.organization_id == organization_id)
        ).first():
            suffix += 1
        name = f"{name} ({suffix})"

    return MetricGenerateResponse(
        name=name,
        description=(parsed.get("description") or "").strip()[:1000],
        metric_type=metric_type,
        custom_data_type=custom_data_type,
        custom_config=custom_config,
        supported_surfaces=supported,
        enabled_surfaces=enabled_surfaces,
        suggested_tags=[str(t) for t in (parsed.get("suggested_tags") or [])][:8],
    )

