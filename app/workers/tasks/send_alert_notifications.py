"""Deliver alert notifications asynchronously."""

from __future__ import annotations

from uuid import UUID

from app.database import SessionLocal
from app.workers.config import celery_app


@celery_app.task(name="send_alert_notifications", bind=True, max_retries=3)
def send_alert_notifications_task(
    self,
    alert_id: str,
    history_id: str,
    triggered_value: float,
) -> dict:
    from app.models.database import Alert, AlertHistory
    from app.services.alerts.alert_evaluation_service import (
        OPEN_INCIDENT_STATUSES,
        alert_evaluation_service,
    )

    db = SessionLocal()
    try:
        alert = db.query(Alert).filter(Alert.id == UUID(alert_id)).first()
        history = (
            db.query(AlertHistory)
            .filter(AlertHistory.id == UUID(history_id))
            .with_for_update()
            .first()
        )
        if not alert or not history:
            return {"error": "alert or history not found"}

        ctx = dict(getattr(history, "context_data", None) or {})
        reserved = bool(ctx.pop("notification_delivery_pending", False))
        history.context_data = ctx

        if history.status not in OPEN_INCIDENT_STATUSES:
            db.commit()
            return {"skipped": f"incident status is {history.status}"}
        if not alert_evaluation_service._should_notify_for_incident(alert, history):
            db.commit()
            return {"skipped": "notification no longer due for incident state"}
        if not reserved:
            db.commit()
            return {"skipped": "notification was not reserved"}

        results = alert_evaluation_service.deliver_notifications_for_history(
            alert, history, triggered_value, db
        )
        return {
            "history_id": history_id,
            "successful": sum(1 for r in results if r.get("success")),
            "total": len(results),
        }
    except Exception as exc:
        db.rollback()
        raise self.retry(exc=exc, countdown=30)
    finally:
        db.close()
