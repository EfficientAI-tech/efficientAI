"""Celery task: refresh USD/INR display FX rate."""

from __future__ import annotations

from app.workers.config import celery_app


@celery_app.task(name="refresh_fx_rates")
def refresh_fx_rates_task() -> dict:
    from app.services.usage.fx_rates import refresh_usd_inr_rate

    return refresh_usd_inr_rate()
