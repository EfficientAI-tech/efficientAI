"""Dispatch due org cron jobs to Celery workers (Beat-driven, no self-scheduling)."""

from __future__ import annotations

from loguru import logger

from app.database import SessionLocal
from app.workers.config import celery_app


@celery_app.task(name="dispatch_cron_jobs")
def dispatch_cron_jobs_task() -> dict:
    from app.services.cron.dispatcher_lock import (
        acquire_dispatcher_run_lock,
        release_dispatcher_run_lock,
    )
    from app.services.cron.job_dispatch import (
        advance_cron_job,
        enqueue_cron_job,
        list_due_cron_jobs,
    )

    if not acquire_dispatcher_run_lock():
        return {"skipped": "locked"}

    dispatched: list[dict] = []
    db = SessionLocal()
    try:
        for job in list_due_cron_jobs(db):
            try:
                meta = enqueue_cron_job(job)
                advance_cron_job(db, job)
                db.commit()
                dispatched.append({"job_id": str(job.id), "job_type": job.job_type, **meta})
            except Exception as exc:
                db.rollback()
                logger.warning("cron dispatch failed for job {}: {}", job.id, exc)
    finally:
        db.close()
        release_dispatcher_run_lock()

    return {"dispatched": len(dispatched), "jobs": dispatched}
