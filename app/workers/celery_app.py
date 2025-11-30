"""Celery application configuration and task definitions."""

import time
from datetime import datetime
from celery import Celery
from app.config import settings
from app.database import SessionLocal
from app.services.evaluation_service import evaluation_service
from uuid import UUID

# Create Celery app
celery_app = Celery(
    "efficientai",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

# Celery configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes
    task_soft_time_limit=25 * 60,  # 25 minutes
)


@celery_app.task(name="process_evaluation", bind=True, max_retries=3)
def process_evaluation_task(self, evaluation_id: str):
    """
    Celery task to process an evaluation.

    Args:
        self: Task instance
        evaluation_id: Evaluation ID as string

    Returns:
        Dictionary with evaluation results
    """
    db = SessionLocal()
    try:
        eval_id = UUID(evaluation_id)
        result = evaluation_service.process_evaluation(eval_id, db)
        return result
    except Exception as exc:
        # Retry on failure
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()


@celery_app.task(name="process_batch_evaluation")
def process_batch_evaluation_task(batch_id: str, evaluation_ids: list[str]):
    """
    Celery task to process a batch of evaluations.

    Args:
        batch_id: Batch job ID
        evaluation_ids: List of evaluation IDs as strings

    Returns:
        Dictionary with batch processing results
    """
    db = SessionLocal()
    try:
        from app.models.database import BatchJob, BatchStatus

        batch = db.query(BatchJob).filter(BatchJob.id == UUID(batch_id)).first()
        if not batch:
            return {"error": "Batch job not found"}

        batch.status = BatchStatus.PROCESSING
        batch.started_at = datetime.utcnow()
        db.commit()

        results = []
        processed = 0
        failed = 0

        for eval_id_str in evaluation_ids:
            try:
                eval_id = UUID(eval_id_str)
                result = evaluation_service.process_evaluation(eval_id, db)
                results.append(result)
                processed += 1
            except Exception as e:
                failed += 1
                results.append({"evaluation_id": eval_id_str, "error": str(e)})

        # Update batch status
        batch.processed_files = processed
        batch.failed_files = failed
        batch.status = BatchStatus.COMPLETED if failed == 0 else BatchStatus.FAILED
        batch.completed_at = datetime.utcnow()
        db.commit()

        return {
            "batch_id": batch_id,
            "processed": processed,
            "failed": failed,
            "results": results,
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        db.close()


@celery_app.task(name="process_evaluator_result", bind=True, max_retries=3)
def process_evaluator_result_task(self, result_id: str):
    """
    Celery task to process an evaluator result: transcribe audio and evaluate metrics.
    
    Args:
        self: Task instance
        result_id: EvaluatorResult ID as string
        
    Returns:
        Dictionary with processing results
    """
    db = SessionLocal()
    try:
        from app.models.database import EvaluatorResult, EvaluatorResultStatus, Metric
        from app.services.s3_service import s3_service
        from app.services.audio_service import AudioService
        import tempfile
        import os
        
        result_uuid = UUID(result_id)
        result = db.query(EvaluatorResult).filter(EvaluatorResult.id == result_uuid).first()
        
        if not result:
            return {"error": "Evaluator result not found"}
        
        # Update status to IN_PROGRESS
        result.status = EvaluatorResultStatus.IN_PROGRESS
        result.celery_task_id = self.request.id
        db.commit()
        
        try:
            # Step 1: Download audio from S3
            if not result.audio_s3_key:
                raise ValueError("No audio S3 key found")
            
            # Download audio file
            audio_data = s3_service.download_file_by_key(result.audio_s3_key)
            
            # Save to temp file for processing
            with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as tmp_file:
                tmp_file.write(audio_data)
                tmp_audio_path = tmp_file.name
            
            try:
                # Step 2: Transcribe audio
                # TODO: Integrate with transcription service (e.g., OpenAI Whisper, AWS Transcribe)
                # For now, we'll use a placeholder
                audio_service = AudioService()
                # transcription = audio_service.transcribe(tmp_audio_path)  # Implement this
                transcription = "Transcription placeholder - implement transcription service"
                
                result.transcription = transcription
                
                # Step 3: Get enabled metrics for the organization
                enabled_metrics = db.query(Metric).filter(
                    Metric.organization_id == result.organization_id,
                    Metric.enabled == True
                ).all()
                
                # Step 4: Evaluate against enabled metrics
                metric_scores = {}
                for metric in enabled_metrics:
                    # TODO: Implement actual metric evaluation logic
                    # This is a placeholder - implement based on metric type
                    if metric.metric_type.value == "rating":
                        # Evaluate rating metric (1-5 or 1-10 scale)
                        score = 4.0  # Placeholder
                    elif metric.metric_type.value == "boolean":
                        # Evaluate boolean metric
                        score = True  # Placeholder
                    elif metric.metric_type.value == "number":
                        # Evaluate number metric
                        score = 85.0  # Placeholder
                    else:
                        score = None
                    
                    metric_scores[str(metric.id)] = {
                        "value": score,
                        "type": metric.metric_type.value,
                        "metric_name": metric.name
                    }
                
                result.metric_scores = metric_scores
                result.status = EvaluatorResultStatus.COMPLETED
                
            finally:
                # Clean up temp file
                if os.path.exists(tmp_audio_path):
                    os.unlink(tmp_audio_path)
            
            db.commit()
            return {
                "result_id": result_id,
                "status": "completed",
                "transcription": transcription,
                "metrics_evaluated": len(metric_scores)
            }
            
        except Exception as e:
            # Mark as failed
            result.status = EvaluatorResultStatus.FAILED
            result.error_message = str(e)
            db.commit()
            raise
            
    except Exception as exc:
        # Retry on failure
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()
