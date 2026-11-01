"""Celery task: flush Redis LLM usage counters into catalog rollups."""

from __future__ import annotations

from loguru import logger

from app.database import SessionLocal
from app.workers.config import celery_app


@celery_app.task(name="flush_usage_counters")
def flush_usage_counters_task() -> dict:
    from app.services.billing.flexprice_buffer import flush_buffered_flexprice_events
    from app.services.call_imports.eval_flexprice_billing import (
        republish_sealed_recording_batches,
    )
    from app.services.usage.llm_usage import flush_all_usage_to_catalog

    try:
        republish_sealed_recording_batches()
    except Exception as exc:
        logger.warning("Flexprice sealed batch republish failed: {}", exc)
    flexprice_stats = flush_buffered_flexprice_events()
    flushed = flush_all_usage_to_catalog(SessionLocal)
    if flushed:
        logger.info("Flushed {} LLM usage rollup buckets", flushed)
    if flexprice_stats.get("flushed"):
        logger.info(
            "Flushed {} buffered Flexprice events ({} failed, {} pending)",
            flexprice_stats["flushed"],
            flexprice_stats.get("failed", 0),
            flexprice_stats.get("pending", 0),
        )
    return {
        "flushed_buckets": flushed,
        "flexprice_flushed": flexprice_stats.get("flushed", 0),
        "flexprice_pending": flexprice_stats.get("pending", 0),
    }
