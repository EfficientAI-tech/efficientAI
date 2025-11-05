"""Evaluation routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID
from app.database import get_db
from app.dependencies import get_api_key, get_organization_id
from app.models.database import Evaluation, EvaluationStatus
from app.models.schemas import (
    EvaluationCreate,
    EvaluationResponse,
    EvaluationStatusResponse,
    MessageResponse,
)
from app.workers.celery_app import process_evaluation_task
from app.core.exceptions import EvaluationNotFoundError

router = APIRouter(prefix="/evaluations", tags=["Evaluations"])


@router.post("/create", response_model=EvaluationResponse, status_code=201)
def create_evaluation(
    evaluation_data: EvaluationCreate,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """
    Create a new evaluation job.

    Args:
        evaluation_data: Evaluation creation data
        api_key: Validated API key
        organization_id: Organization ID from API key
        db: Database session

    Returns:
        Created evaluation
    """
    # Verify audio file exists and belongs to organization
    from app.models.database import AudioFile

    audio_file = db.query(AudioFile).filter(
        AudioFile.id == evaluation_data.audio_id,
        AudioFile.organization_id == organization_id
    ).first()
    if not audio_file:
        raise HTTPException(status_code=404, detail="Audio file not found")

    # Create evaluation record
    evaluation = Evaluation(
        organization_id=organization_id,
        audio_id=evaluation_data.audio_id,
        reference_text=evaluation_data.reference_text,
        evaluation_type=evaluation_data.evaluation_type,
        model_name=evaluation_data.model_name,
        metrics_requested=evaluation_data.metrics,
        status=EvaluationStatus.PENDING,
    )
    db.add(evaluation)
    db.commit()
    db.refresh(evaluation)

    # Queue async task
    process_evaluation_task.delay(str(evaluation.id))

    return evaluation


@router.get("/{evaluation_id}", response_model=EvaluationResponse)
def get_evaluation(
    evaluation_id: str,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """
    Get evaluation details.

    Args:
        evaluation_id: Evaluation ID
        api_key: Validated API key
        organization_id: Organization ID from API key
        db: Database session

    Returns:
        Evaluation details
    """
    try:
        eval_id = UUID(evaluation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid evaluation ID format")

    evaluation = db.query(Evaluation).filter(
        Evaluation.id == eval_id,
        Evaluation.organization_id == organization_id
    ).first()
    if not evaluation:
        raise HTTPException(status_code=404, detail="Evaluation not found")

    return evaluation


@router.get("", response_model=List[EvaluationResponse])
def list_evaluations(
    skip: int = 0,
    limit: int = 100,
    status: EvaluationStatus = None,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """
    List evaluations (paginated, optionally filtered by status) for the organization.

    Args:
        skip: Number of records to skip
        limit: Maximum number of records to return
        status: Optional status filter
        api_key: Validated API key
        organization_id: Organization ID from API key
        db: Database session

    Returns:
        List of evaluations
    """
    query = db.query(Evaluation).filter(Evaluation.organization_id == organization_id)
    if status:
        query = query.filter(Evaluation.status == status)

    evaluations = query.order_by(Evaluation.created_at.desc()).offset(skip).limit(limit).all()
    return evaluations


@router.post("/{evaluation_id}/cancel", response_model=MessageResponse)
def cancel_evaluation(
    evaluation_id: str,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """
    Cancel a pending evaluation.

    Args:
        evaluation_id: Evaluation ID
        api_key: Validated API key
        organization_id: Organization ID from API key
        db: Database session

    Returns:
        Success message
    """
    try:
        eval_id = UUID(evaluation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid evaluation ID format")

    evaluation = db.query(Evaluation).filter(
        Evaluation.id == eval_id,
        Evaluation.organization_id == organization_id
    ).first()
    if not evaluation:
        raise HTTPException(status_code=404, detail="Evaluation not found")

    if evaluation.status != EvaluationStatus.PENDING:
        raise HTTPException(
            status_code=400, detail=f"Cannot cancel evaluation with status: {evaluation.status}"
        )

    evaluation.status = EvaluationStatus.CANCELLED
    db.commit()

    return {"message": "Evaluation cancelled successfully"}


@router.delete("/{evaluation_id}", response_model=MessageResponse)
def delete_evaluation(
    evaluation_id: str,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """
    Delete an evaluation.

    Args:
        evaluation_id: Evaluation ID
        api_key: Validated API key
        organization_id: Organization ID from API key
        db: Database session

    Returns:
        Success message
    """
    try:
        eval_id = UUID(evaluation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid evaluation ID format")

    evaluation = db.query(Evaluation).filter(
        Evaluation.id == eval_id,
        Evaluation.organization_id == organization_id
    ).first()
    if not evaluation:
        raise HTTPException(status_code=404, detail="Evaluation not found")

    # Delete associated result if exists
    if evaluation.result:
        db.delete(evaluation.result)

    db.delete(evaluation)
    db.commit()

    return {"message": "Evaluation deleted successfully"}

