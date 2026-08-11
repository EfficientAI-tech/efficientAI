"""Celery task: flush Redis LLM usage counters into catalog rollups."""

from __future__ import annotations

from loguru import logger

from app.database import SessionLocal
from app.workers.config import celery_app


@celery_app.task(name="flush_usage_counters")
def flush_usage_counters_task() -> dict:
    from app.services.usage.llm_usage import flush_all_usage_to_catalog

    flushed = flush_all_usage_to_catalog(SessionLocal)
    if flushed:
        logger.info("Flushed {} LLM usage rollup buckets", flushed)
    return {"flushed_buckets": flushed}
