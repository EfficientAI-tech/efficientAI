"""Batch processing routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import uuid4
from typing import List
from app.database import get_db
from app.dependencies import get_api_key
from app.models.database import BatchJob, BatchStatus, Evaluation, EvaluationStatus
from app.models.schemas import (
    BatchCreate,
    BatchResponse,
    BatchResultsResponse,
    EvaluationResultResponse,
    MessageResponse,
)
from app.workers.celery_app import process_batch_evaluation_task
from app.core.exceptions import AudioFileNotFoundError

router = APIRouter(prefix="/batch", tags=["Batch"])


@router.post("/create", response_model=BatchResponse, status_code=201)
def create_batch(
    batch_data: BatchCreate,
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """
    Create a batch evaluation job.

    Args:
        batch_data: Batch creation data
        api_key: Validated API key
        db: Database session

    Returns:
        Created batch job
    """
    from app.models.database import AudioFile

    # Verify all audio files exist
    audio_files = db.query(AudioFile).filter(AudioFile.id.in_(batch_data.audio_ids)).all()
    if len(audio_files) != len(batch_data.audio_ids):
        raise HTTPException(status_code=404, detail="One or more audio files not found")

    # Create batch job
    batch_id = uuid4()
    batch = BatchJob(
        id=batch_id,
        status=BatchStatus.PENDING,
        total_files=len(batch_data.audio_ids),
        processed_files=0,
        failed_files=0,
        evaluation_type=batch_data.evaluation_type,
        model_name=batch_data.model_name,
        metrics_requested=batch_data.metrics,
    )
    db.add(batch)
    db.commit()

    # Create individual evaluations
    evaluation_ids = []
    for audio_id in batch_data.audio_ids:
        reference_text = (
            batch_data.reference_texts.get(str(audio_id)) if batch_data.reference_texts else None
        )

        evaluation = Evaluation(
            audio_id=audio_id,
            reference_text=reference_text,
            evaluation_type=batch_data.evaluation_type,
            model_name=batch_data.model_name,
            metrics_requested=batch_data.metrics,
            status=EvaluationStatus.PENDING,
        )
        db.add(evaluation)
        db.flush()
        evaluation_ids.append(str(evaluation.id))

    # Update batch with evaluation IDs
    batch.evaluation_ids = evaluation_ids
    db.commit()
    db.refresh(batch)

    # Queue async batch task
    process_batch_evaluation_task.delay(str(batch_id), evaluation_ids)

    return batch


@router.get("/{batch_id}", response_model=BatchResponse)
def get_batch(
    batch_id: str,
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """
    Get batch job status.

    Args:
        batch_id: Batch job ID
        api_key: Validated API key
        db: Database session

    Returns:
        Batch job details
    """
    from uuid import UUID

    try:
        batch_uuid = UUID(batch_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid batch ID format")

    batch = db.query(BatchJob).filter(BatchJob.id == batch_uuid).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch job not found")

    return batch


@router.get("/{batch_id}/results", response_model=BatchResultsResponse)
def get_batch_results(
    batch_id: str,
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """
    Get batch results summary.

    Args:
        batch_id: Batch job ID
        api_key: Validated API key
        db: Database session

    Returns:
        Batch results summary
    """
    from uuid import UUID
    from app.models.database import EvaluationResult

    try:
        batch_uuid = UUID(batch_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid batch ID format")

    batch = db.query(BatchJob).filter(BatchJob.id == batch_uuid).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch job not found")

    # Get all evaluation results for this batch
    evaluation_ids = batch.evaluation_ids or []
    results = []

    for eval_id_str in evaluation_ids:
        try:
            eval_id = UUID(eval_id_str)
        except ValueError:
            continue

        result = db.query(EvaluationResult).filter(EvaluationResult.evaluation_id == eval_id).first()
        evaluation = db.query(Evaluation).filter(Evaluation.id == eval_id).first()

        if result and evaluation:
            results.append(
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

    return BatchResultsResponse(
        batch_id=batch_uuid,
        status=batch.status,
        total_files=batch.total_files,
        processed_files=batch.processed_files,
        failed_files=batch.failed_files,
        aggregated_metrics=batch.aggregated_metrics,
        individual_results=results,
    )


@router.post("/{batch_id}/export")
def export_batch_results(
    batch_id: str,
    format: str = "json",
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """
    Export batch results as CSV or JSON.

    Args:
        batch_id: Batch job ID
        format: Export format (json or csv)
        api_key: Validated API key
        db: Database session

    Returns:
        Exported results
    """
    from uuid import UUID
    from app.models.database import EvaluationResult
    from fastapi.responses import Response
    import json
    import csv
    from io import StringIO

    try:
        batch_uuid = UUID(batch_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid batch ID format")

    batch = db.query(BatchJob).filter(BatchJob.id == batch_uuid).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch job not found")

    # Get all evaluation results
    evaluation_ids = batch.evaluation_ids or []
    results_data = []

    for eval_id_str in evaluation_ids:
        try:
            eval_id = UUID(eval_id_str)
        except ValueError:
            continue

        result = db.query(EvaluationResult).filter(EvaluationResult.evaluation_id == eval_id).first()
        evaluation = db.query(Evaluation).filter(Evaluation.id == eval_id).first()

        if result and evaluation:
            results_data.append(
                {
                    "evaluation_id": str(eval_id),
                    "status": evaluation.status.value,
                    "transcript": result.transcript,
                    "metrics": result.metrics,
                    "processing_time": result.processing_time,
                    "model_used": result.model_used,
                }
            )

    if format == "csv":
        # Convert to CSV
        output = StringIO()
        if results_data:
            writer = csv.DictWriter(output, fieldnames=results_data[0].keys())
            writer.writeheader()
            for row in results_data:
                # Convert metrics dict to string
                row_copy = row.copy()
                row_copy["metrics"] = json.dumps(row_copy["metrics"])
                writer.writerow(row_copy)

        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=batch_{batch_id}.csv"},
        )

    else:  # JSON
        return Response(
            content=json.dumps(results_data, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=batch_{batch_id}.json"},
        )

