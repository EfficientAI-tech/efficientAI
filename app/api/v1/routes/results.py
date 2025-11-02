"""Results retrieval routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID
from app.database import get_db
from app.dependencies import get_api_key
from app.models.database import Evaluation, EvaluationResult, EvaluationStatus
from app.models.schemas import (
    EvaluationResultResponse,
    MetricsResponse,
    ComparisonRequest,
    ComparisonResponse,
)
from app.core.exceptions import EvaluationNotFoundError

router = APIRouter(prefix="/results", tags=["Results"])


@router.get("/{evaluation_id}", response_model=EvaluationResultResponse)
def get_evaluation_result(
    evaluation_id: str,
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """
    Get detailed evaluation results.

    Args:
        evaluation_id: Evaluation ID
        api_key: Validated API key
        db: Database session

    Returns:
        Detailed evaluation results
    """
    try:
        eval_id = UUID(evaluation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid evaluation ID format")

    evaluation = db.query(Evaluation).filter(Evaluation.id == eval_id).first()
    if not evaluation:
        raise HTTPException(status_code=404, detail="Evaluation not found")

    result = db.query(EvaluationResult).filter(EvaluationResult.evaluation_id == eval_id).first()

    if not result:
        return EvaluationResultResponse(
            evaluation_id=eval_id,
            status=evaluation.status,
            transcript=None,
            metrics={},
            processing_time=None,
            model_used=None,
            created_at=evaluation.created_at,
        )

    return EvaluationResultResponse(
        evaluation_id=eval_id,
        status=evaluation.status,
        transcript=result.transcript,
        metrics=result.metrics or {},
        processing_time=result.processing_time,
        model_used=result.model_used,
        created_at=result.created_at,
    )


@router.get("/{evaluation_id}/metrics", response_model=MetricsResponse)
def get_metrics(
    evaluation_id: str,
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """
    Get metrics breakdown for an evaluation.

    Args:
        evaluation_id: Evaluation ID
        api_key: Validated API key
        db: Database session

    Returns:
        Metrics breakdown
    """
    try:
        eval_id = UUID(evaluation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid evaluation ID format")

    result = db.query(EvaluationResult).filter(EvaluationResult.evaluation_id == eval_id).first()
    if not result:
        raise HTTPException(status_code=404, detail="Results not found for this evaluation")

    return MetricsResponse(
        evaluation_id=eval_id,
        metrics=result.metrics or {},
        processing_time=result.processing_time,
    )


@router.get("/{evaluation_id}/transcript")
def get_transcript(
    evaluation_id: str,
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """
    Get transcription text for an evaluation.

    Args:
        evaluation_id: Evaluation ID
        api_key: Validated API key
        db: Database session

    Returns:
        Transcription text
    """
    try:
        eval_id = UUID(evaluation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid evaluation ID format")

    result = db.query(EvaluationResult).filter(EvaluationResult.evaluation_id == eval_id).first()
    if not result:
        raise HTTPException(status_code=404, detail="Results not found for this evaluation")

    return {"evaluation_id": str(eval_id), "transcript": result.transcript or ""}


@router.post("/compare", response_model=ComparisonResponse)
def compare_evaluations(
    comparison_data: ComparisonRequest,
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """
    Compare multiple evaluations.

    Args:
        comparison_data: Evaluation IDs to compare
        api_key: Validated API key
        db: Database session

    Returns:
        Comparison results
    """
    evaluation_results = []

    for eval_id_str in comparison_data.evaluation_ids:
        try:
            eval_id = UUID(eval_id_str)
        except ValueError:
            continue

        result = db.query(EvaluationResult).filter(EvaluationResult.evaluation_id == eval_id).first()
        if not result:
            continue

        evaluation = db.query(Evaluation).filter(Evaluation.id == eval_id).first()
        if not evaluation:
            continue

        evaluation_results.append(
            EvaluationResultResponse(
                evaluation_id=eval_id,
                status=evaluation.status,
                transcript=result.transcript,
                metrics=result.metrics or {},
                processing_time=result.processing_time,
                model_used=result.model_used,
                created_at=result.created_at,
            )
        )

    if len(evaluation_results) < 2:
        raise HTTPException(
            status_code=400, detail="At least 2 valid evaluation results required for comparison"
        )

    # Calculate comparison metrics
    comparison_metrics = {}
    if evaluation_results:
        # Compare metrics across evaluations
        metric_names = set()
        for result in evaluation_results:
            if result.metrics:
                metric_names.update(result.metrics.keys())

        comparison_metrics = {}
        for metric_name in metric_names:
            values = [
                result.metrics.get(metric_name)
                for result in evaluation_results
                if result.metrics and result.metrics.get(metric_name) is not None
            ]
            if values:
                comparison_metrics[f"{metric_name}_min"] = min(values)
                comparison_metrics[f"{metric_name}_max"] = max(values)
                comparison_metrics[f"{metric_name}_avg"] = sum(values) / len(values)

    return ComparisonResponse(
        evaluations=evaluation_results,
        comparison_metrics=comparison_metrics,
    )

