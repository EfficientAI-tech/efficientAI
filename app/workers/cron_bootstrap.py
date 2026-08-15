"""Bootstrap cron dispatcher on worker startup."""

from __future__ import annotations

from celery.signals import worker_ready
from loguru import logger


@worker_ready.connect
def _bootstrap_cron_dispatcher(sender, **kwargs):
    try:
        from app.services.cron.dispatcher_lock import try_acquire_dispatcher_leader

        if not try_acquire_dispatcher_leader():
            return
        from app.workers.tasks.dispatch_cron_jobs import dispatch_cron_jobs_task

        dispatch_cron_jobs_task.apply_async(countdown=5)
        logger.info("Cron dispatcher bootstrap enqueued")
    except Exception as exc:
        logger.warning("Cron dispatcher bootstrap skipped: {}", exc)
