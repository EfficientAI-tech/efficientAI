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

