"""Celery task: evaluate all active alerts."""

from __future__ import annotations

from app.database import SessionLocal
from app.workers.config import celery_app


@celery_app.task(name="evaluate_alerts")
def evaluate_alerts_task() -> dict:
    from app.services.alerts.alert_evaluation_service import alert_evaluation_service

    db = SessionLocal()
    try:
        return alert_evaluation_service.evaluate_all_alerts(db)
    finally:
        db.close()
