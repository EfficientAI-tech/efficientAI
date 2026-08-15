"""Celery task: run evaluator_ids for an org cron job."""

from __future__ import annotations

from uuid import UUID

from app.database import SessionLocal
from app.models.database import CronJob
from app.workers.config import celery_app


@celery_app.task(name="run_cron_evaluator_job")
def run_cron_evaluator_job_task(job_id: str) -> dict:
    from app.services.cron.job_dispatch import run_evaluator_cron_job

    db = SessionLocal()
    try:
        job = db.query(CronJob).filter(CronJob.id == UUID(job_id)).first()
        if job is None:
            return {"error": "job not found", "job_id": job_id}
        return run_evaluator_cron_job(db, job)
    finally:
        db.close()
