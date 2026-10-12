"""Celery task: evaluate all active alerts (coordinator)."""

from __future__ import annotations

from loguru import logger

from app.database import SessionLocal
from app.workers.config import celery_app


@celery_app.task(name="evaluate_alerts")
def evaluate_alerts_task() -> dict:
    from app.models.database import Alert
    from app.models.enums import AlertStatus
    from app.core.license import is_feature_enabled
    from app.services.alerts.evaluation_lock import (
        acquire_alert_evaluation_lock,
        release_alert_evaluation_lock,
    )
    from app.workers.tasks.evaluate_alerts_for_org import evaluate_alerts_for_org_task

    if not acquire_alert_evaluation_lock():
        logger.info("[AlertEvaluation] Skipping tick: evaluation lock held or Redis unavailable")
        return {"skipped": "locked"}

    db = SessionLocal()
    try:
        org_ids = set()
        for alert in db.query(Alert).filter(Alert.status == AlertStatus.ACTIVE.value).all():
            if is_feature_enabled("alerts", alert.organization_id):
                org_ids.add(str(alert.organization_id))

        dispatched = []
        for org_id in org_ids:
            result = evaluate_alerts_for_org_task.delay(org_id)
            dispatched.append({"organization_id": org_id, "celery_task_id": result.id})

        return {"organizations": len(dispatched), "dispatched": dispatched}
    finally:
        db.close()
        release_alert_evaluation_lock()
