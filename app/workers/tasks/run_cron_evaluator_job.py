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
        result = run_evaluator_cron_job(db, job)
        err = result.get("error")
        tasks = int(result.get("evaluator_tasks") or 0)
        expected = int(result.get("evaluator_ids_expected") or 0)
        if err:
            job.last_run_status = "failed"
            job.last_run_error = str(err)[:2000]
        elif tasks == 0:
            job.last_run_status = "failed"
            job.last_run_error = "no evaluator tasks enqueued"
        elif expected > 0 and tasks < expected:
            job.last_run_status = "failed"
            job.last_run_error = (
                f"partial enqueue: {tasks}/{expected} evaluator runs queued"
            )[:2000]
        else:
            job.last_run_status = "success"
            job.last_run_error = None
        db.commit()
        return result
    finally:
        db.close()
