"""Evaluate active alerts for one organization."""

from __future__ import annotations

from uuid import UUID

from app.database import SessionLocal
from app.workers.config import celery_app


@celery_app.task(name="evaluate_alerts_for_org")
def evaluate_alerts_for_org_task(organization_id: str) -> dict:
    from app.services.alerts.alert_evaluation_service import alert_evaluation_service

    db = SessionLocal()
    try:
        return alert_evaluation_service.evaluate_organization_alerts(
            db, UUID(organization_id)
        )
    finally:
        db.close()
