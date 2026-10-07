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
                task_name = meta.get("task")
                celery_id = meta.get("celery_task_id")
                if task_name == "unknown" or not celery_id:
                    job.last_dispatch_status = "failed"
                    job.last_dispatch_error = (
                        meta.get("error")
                        or f"enqueue failed for job_type={job.job_type}"
                    )
                    job.last_dispatch_celery_task_id = None
                    db.commit()
                    dispatched.append(
                        {
                            "job_id": str(job.id),
                            "job_type": job.job_type,
                            "dispatch_status": "failed",
                            **meta,
                        }
                    )
                    continue

                job.last_dispatch_status = "enqueued"
                job.last_dispatch_celery_task_id = celery_id
                job.last_dispatch_error = None
                advance_cron_job(db, job)
                db.commit()
                dispatched.append(
                    {
                        "job_id": str(job.id),
                        "job_type": job.job_type,
                        "dispatch_status": "enqueued",
                        **meta,
                    }
                )
            except Exception as exc:
                db.rollback()
                logger.warning("cron dispatch failed for job {}: {}", job.id, exc)
                try:
                    job.last_dispatch_status = "failed"
                    job.last_dispatch_error = str(exc)
                    db.commit()
                except Exception:
                    db.rollback()
    finally:
        db.close()
        release_dispatcher_run_lock()

    return {"dispatched": len(dispatched), "jobs": dispatched}
