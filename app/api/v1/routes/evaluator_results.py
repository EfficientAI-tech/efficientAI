"""Evaluator Results routes."""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_
from uuid import UUID
from typing import List, Optional

from app.database import get_db
from app.dependencies import get_organization_id, get_api_key
from app.models.database import EvaluatorResult, Evaluator, Metric, EvaluatorResultStatus, Scenario
from app.workers.celery_app import process_evaluator_result_task
import random
from app.models.schemas import (
    EvaluatorResultResponse,
    EvaluatorResultCreate,
    EvaluatorResultCreateManual,
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
    include_relations: bool = True,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Get a specific evaluator result by ID (UUID) or result_id (6-digit)."""
    from app.models.database import Agent, Persona, Scenario, Evaluator
    from app.models.schemas import AgentResponse, PersonaResponse, ScenarioResponse, EvaluatorResponse
    
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
    
    # Build response
    response_data = {
        "id": result.id,
        "result_id": result.result_id,
        "organization_id": result.organization_id,
        "evaluator_id": result.evaluator_id,
        "agent_id": result.agent_id,
        "persona_id": result.persona_id,
        "scenario_id": result.scenario_id,
        "name": result.name,
        "timestamp": result.timestamp,
        "duration_seconds": result.duration_seconds,
        "status": result.status,
        "audio_s3_key": result.audio_s3_key,
        "transcription": result.transcription,
        "speaker_segments": result.speaker_segments,
        "metric_scores": result.metric_scores,
        "celery_task_id": result.celery_task_id,
        "error_message": result.error_message,
        "created_at": result.created_at,
        "updated_at": result.updated_at,
        "created_by": result.created_by,
    }
    
    # Include related entities if requested
    if include_relations:
        # Get Agent
        agent = db.query(Agent).filter(Agent.id == result.agent_id).first()
        if agent:
            response_data["agent"] = AgentResponse.model_validate(agent)
        
        # Get Persona
        persona = db.query(Persona).filter(Persona.id == result.persona_id).first()
        if persona:
            response_data["persona"] = PersonaResponse.model_validate(persona)
        
        # Get Scenario
        scenario = db.query(Scenario).filter(Scenario.id == result.scenario_id).first()
        if scenario:
            response_data["scenario"] = ScenarioResponse.model_validate(scenario)
        
        # Get Evaluator
        evaluator = db.query(Evaluator).filter(Evaluator.id == result.evaluator_id).first()
        if evaluator:
            response_data["evaluator"] = EvaluatorResponse.model_validate(evaluator)
    
    return EvaluatorResultResponse(**response_data)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_evaluator_result(
    id: str,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Delete a specific evaluator result by ID (UUID) or result_id (6-digit)."""
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
    
    db.delete(result)
    db.commit()
    return None


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_evaluator_results_bulk(
    result_ids: List[str] = Query(...),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Delete multiple evaluator results by their IDs."""
    deleted_count = 0
    
    for result_id in result_ids:
        try:
            # Try as UUID first
            result_uuid = UUID(result_id)
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
                    EvaluatorResult.result_id == result_id,
                    EvaluatorResult.organization_id == organization_id
                )
            ).first()
        
        if result:
            db.delete(result)
            deleted_count += 1
    
    db.commit()
    return None


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


@router.post("", response_model=EvaluatorResultResponse, status_code=status.HTTP_201_CREATED)
def create_evaluator_result_manual(
    result_data: EvaluatorResultCreateManual,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """
    Manually create an evaluator result from an existing audio file.
    This will trigger transcription and metric evaluation automatically.
    """
    # Get evaluator
    evaluator = db.query(Evaluator).filter(
        Evaluator.id == result_data.evaluator_id,
        Evaluator.organization_id == organization_id
    ).first()
    
    if not evaluator:
        raise HTTPException(status_code=404, detail="Evaluator not found")
    
    # Get scenario for name
    scenario = db.query(Scenario).filter(Scenario.id == evaluator.scenario_id).first()
    scenario_name = scenario.name if scenario else "Unknown Scenario"
    
    # Generate unique 6-digit result ID
    max_attempts = 100
    result_id = None
    for _ in range(max_attempts):
        candidate_id = f"{random.randint(100000, 999999)}"
        existing = db.query(EvaluatorResult).filter(EvaluatorResult.result_id == candidate_id).first()
        if not existing:
            result_id = candidate_id
            break
    
    if not result_id:
        raise HTTPException(status_code=500, detail="Failed to generate unique result ID")
    
    # Create evaluator result with QUEUED status
    evaluator_result = EvaluatorResult(
        result_id=result_id,
        organization_id=organization_id,
        evaluator_id=evaluator.id,
        agent_id=evaluator.agent_id,
        persona_id=evaluator.persona_id,
        scenario_id=evaluator.scenario_id,
        name=scenario_name,
        duration_seconds=result_data.duration_seconds,
        status=EvaluatorResultStatus.QUEUED.value,  # Use .value to get the string
        audio_s3_key=result_data.audio_s3_key
    )
    
    db.add(evaluator_result)
    db.commit()
    db.refresh(evaluator_result)
    
    # Trigger Celery task for transcription and evaluation
    try:
        task = process_evaluator_result_task.delay(str(evaluator_result.id))
        evaluator_result.celery_task_id = task.id
        db.commit()
    except Exception as e:
        # If task creation fails, still return the result but log the error
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to trigger Celery task for evaluator result {result_id}: {e}")
    
    return evaluator_result

