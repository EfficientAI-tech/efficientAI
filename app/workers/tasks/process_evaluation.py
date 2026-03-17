"""Celery task: process evaluation.

Uses lazy imports to avoid loading heavy dependencies (whisper, librosa)
at module import time.
"""

from uuid import UUID

from app.database import SessionLocal

from app.workers.config import celery_app


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
    # Lazy import to avoid loading whisper/librosa at worker startup
    from app.services.evaluation.evaluation_service import evaluation_service
    
    db = SessionLocal()
    try:
        eval_id = UUID(evaluation_id)
        result = evaluation_service.process_evaluation(eval_id, db)
        return result
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()
