"""Celery task: prune OSS usage rollup rows beyond history window."""

from __future__ import annotations

from loguru import logger

from app.database import SessionLocal
from app.workers.config import celery_app


@celery_app.task(name="prune_oss_usage_history")
def prune_oss_usage_history_task() -> dict:
    from app.services.usage.retention import prune_oss_usage_history

    db = SessionLocal()
    try:
        result = prune_oss_usage_history(db)
    finally:
        db.close()
    if result.get("deleted"):
        logger.info("prune_oss_usage_history_task {}", result)
    return result
