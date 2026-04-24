"""Metrics routes."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import and_
from uuid import UUID
from typing import List, Optional

from app.database import get_db
from app.dependencies import get_organization_id, get_api_key
from app.models.database import Metric, MetricType, MetricTrigger
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
        },
    ]

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

