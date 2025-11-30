"""Evaluator Results routes."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import and_
from uuid import UUID
from typing import List, Optional

from app.database import get_db
from app.dependencies import get_organization_id, get_api_key
from app.models.database import EvaluatorResult, Evaluator, Metric
from app.models.schemas import (
    EvaluatorResultResponse,
    EvaluatorResultCreate,
    EvaluatorResultUpdate,
)

router = APIRouter(prefix="/evaluator-results", tags=["evaluator-results"])


@router.get("", response_model=List[EvaluatorResultResponse])
def list_evaluator_results(
    skip: int = 0,
    limit: int = 100,
    evaluator_id: Optional[str] = None,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """List all evaluator results for the organization."""
    query = db.query(EvaluatorResult).filter(
        EvaluatorResult.organization_id == organization_id
    )
    
    if evaluator_id:
        try:
            evaluator_uuid = UUID(evaluator_id)
            query = query.filter(EvaluatorResult.evaluator_id == evaluator_uuid)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid evaluator_id")
    
    results = query.order_by(EvaluatorResult.timestamp.desc()).offset(skip).limit(limit).all()
    return results


@router.get("/{id}", response_model=EvaluatorResultResponse)
def get_evaluator_result(
    id: str,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Get a specific evaluator result by ID (UUID) or result_id (6-digit)."""
    try:
        # Try as UUID first
        result_uuid = UUID(id)
        result = db.query(EvaluatorResult).filter(
            and_(
                EvaluatorResult.id == result_uuid,
                EvaluatorResult.organization_id == organization_id
            )
        ).first()
    except ValueError:
        # Try as 6-digit ID
        result = db.query(EvaluatorResult).filter(
            and_(
                EvaluatorResult.result_id == id,
                EvaluatorResult.organization_id == organization_id
            )
        ).first()
    
    if not result:
        raise HTTPException(status_code=404, detail="Evaluator result not found")
    
    return result


@router.get("/{id}/metrics", response_model=dict)
def get_evaluator_result_metrics(
    id: str,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Get metric scores for an evaluator result with metric details."""
    try:
        result_uuid = UUID(id)
        result = db.query(EvaluatorResult).filter(
            and_(
                EvaluatorResult.id == result_uuid,
                EvaluatorResult.organization_id == organization_id
            )
        ).first()
    except ValueError:
        result = db.query(EvaluatorResult).filter(
            and_(
                EvaluatorResult.result_id == id,
                EvaluatorResult.organization_id == organization_id
            )
        ).first()
    
    if not result:
        raise HTTPException(status_code=404, detail="Evaluator result not found")
    
    # Get all enabled metrics for the organization
    enabled_metrics = db.query(Metric).filter(
        Metric.organization_id == organization_id,
        Metric.enabled == True
    ).all()
    
    # Build response with metric details
    metrics_response = {}
    if result.metric_scores:
        for metric_id, score_data in result.metric_scores.items():
            metric = next((m for m in enabled_metrics if str(m.id) == metric_id), None)
            if metric:
                metrics_response[metric.name] = {
                    "value": score_data.get("value"),
                    "type": score_data.get("type"),
                    "metric_id": metric_id,
                    "description": metric.description
                }
    
    return {
        "result_id": result.result_id,
        "metrics": metrics_response
    }

