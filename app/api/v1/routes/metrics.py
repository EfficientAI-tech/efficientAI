"""Metrics routes."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import and_
from uuid import UUID
from typing import List

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

    metric = Metric(
        organization_id=organization_id,
        name=metric_data.name,
        description=metric_data.description,
        metric_type=metric_data.metric_type,
        trigger=metric_data.trigger,
        enabled=metric_data.enabled,
        is_default=False,
    )
    db.add(metric)
    db.commit()
    db.refresh(metric)

    return metric


@router.get("", response_model=List[MetricResponse])
def list_metrics(
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """List all metrics for the organization."""
    metrics = db.query(Metric).filter(
        Metric.organization_id == organization_id
    ).order_by(Metric.is_default.desc(), Metric.created_at.desc()).all()
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

    db.commit()
    db.refresh(metric)

    return metric


# Deprecated default metrics that can be deleted
DEPRECATED_DEFAULT_METRICS = {"Response Time", "Customer Satisfaction"}


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
        # Qualitative Metrics (LLM-evaluated subjective assessments)
        {
            "name": "Follow Instructions",
            "description": "Measures how well the agent follows instructions and guidelines",
            "metric_type": MetricType.RATING,
            "trigger": MetricTrigger.ALWAYS,
            "enabled": True,
        },
        {
            "name": "Clarity and Empathy",
            "description": "Evaluates the clarity of communication and empathetic responses",
            "metric_type": MetricType.RATING,
            "trigger": MetricTrigger.ALWAYS,
            "enabled": True,
        },
        {
            "name": "Professionalism",
            "description": "Assesses the professional tone and behavior throughout the conversation",
            "metric_type": MetricType.RATING,
            "trigger": MetricTrigger.ALWAYS,
            "enabled": True,
        },
        {
            "name": "Problem Resolution",
            "description": "Measures the effectiveness in resolving customer issues",
            "metric_type": MetricType.BOOLEAN,
            "trigger": MetricTrigger.ALWAYS,
            "enabled": True,
        },
        # Quantitative Metrics (Audio analysis using Parselmouth - objective measurements)
        {
            "name": "Pitch Variance",
            "description": "Measures F0 (fundamental frequency) variation in Hz - indicates prosodic expressiveness. Higher values suggest more expressive speech.",
            "metric_type": MetricType.NUMBER,
            "trigger": MetricTrigger.ALWAYS,
            "enabled": True,
        },
        {
            "name": "Jitter",
            "description": "Cycle-to-cycle pitch period variation as percentage - indicates vocal stability. Lower values (< 1%) indicate stable voice.",
            "metric_type": MetricType.NUMBER,
            "trigger": MetricTrigger.ALWAYS,
            "enabled": True,
        },
        {
            "name": "Shimmer",
            "description": "Cycle-to-cycle amplitude variation as percentage - indicates voice quality. Lower values (< 3%) indicate consistent voice.",
            "metric_type": MetricType.NUMBER,
            "trigger": MetricTrigger.ALWAYS,
            "enabled": True,
        },
        {
            "name": "HNR",
            "description": "Harmonics-to-Noise Ratio in dB - indicates voice clarity. Higher values (> 20 dB) indicate cleaner voice with less breathiness.",
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
            )
            db.add(metric)
            created_metrics.append(metric)

    db.commit()
    for metric in created_metrics:
        db.refresh(metric)

    return created_metrics

