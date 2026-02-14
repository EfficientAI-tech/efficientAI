"""Alerts routes."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import and_
from uuid import UUID
from typing import List, Optional
from datetime import datetime

from app.database import get_db
from app.dependencies import get_organization_id
from app.models.database import Alert, AlertHistory
from app.models.enums import AlertStatus, AlertHistoryStatus
from app.models.schemas import (
    AlertCreate,
    AlertUpdate,
    AlertResponse,
    AlertHistoryResponse,
    AlertHistoryUpdate,
)
from app.services.alert_evaluation_service import alert_evaluation_service
from app.services.alert_notification_service import alert_notification_service

router = APIRouter(prefix="/alerts", tags=["alerts"])


# ============================================
# ALERT CRUD ENDPOINTS
# ============================================

@router.post("", response_model=AlertResponse, status_code=201)
def create_alert(
    alert_data: AlertCreate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Create a new alert."""
    # Check if alert with same name already exists for this organization
    existing = db.query(Alert).filter(
        and_(
            Alert.name == alert_data.name,
            Alert.organization_id == organization_id
        )
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An alert with this name already exists"
        )

    alert = Alert(
        organization_id=organization_id,
        name=alert_data.name,
        description=alert_data.description,
        metric_type=alert_data.metric_type.value,
        aggregation=alert_data.aggregation.value,
        operator=alert_data.operator.value,
        threshold_value=alert_data.threshold_value,
        time_window_minutes=alert_data.time_window_minutes,
        agent_ids=[str(aid) for aid in alert_data.agent_ids] if alert_data.agent_ids else None,
        notify_frequency=alert_data.notify_frequency.value,
        notify_emails=alert_data.notify_emails,
        notify_webhooks=alert_data.notify_webhooks,
        status=AlertStatus.ACTIVE.value,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)

    return alert


@router.get("", response_model=List[AlertResponse])
def list_alerts(
    status_filter: Optional[AlertStatus] = None,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """List all alerts for the organization."""
    query = db.query(Alert).filter(Alert.organization_id == organization_id)
    
    if status_filter:
        query = query.filter(Alert.status == status_filter.value)
    
    alerts = query.order_by(Alert.created_at.desc()).all()
    return alerts


@router.get("/{alert_id}", response_model=AlertResponse)
def get_alert(
    alert_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Get a specific alert."""
    alert = db.query(Alert).filter(
        and_(
            Alert.id == alert_id,
            Alert.organization_id == organization_id
        )
    ).first()

    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    return alert


@router.put("/{alert_id}", response_model=AlertResponse)
def update_alert(
    alert_id: UUID,
    alert_data: AlertUpdate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Update an alert."""
    alert = db.query(Alert).filter(
        and_(
            Alert.id == alert_id,
            Alert.organization_id == organization_id
        )
    ).first()

    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    # Update fields if provided
    if alert_data.name is not None:
        # Check for name conflicts
        existing = db.query(Alert).filter(
            and_(
                Alert.name == alert_data.name,
                Alert.organization_id == organization_id,
                Alert.id != alert_id
            )
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An alert with this name already exists"
            )
        alert.name = alert_data.name

    if alert_data.description is not None:
        alert.description = alert_data.description

    if alert_data.metric_type is not None:
        alert.metric_type = alert_data.metric_type.value

    if alert_data.aggregation is not None:
        alert.aggregation = alert_data.aggregation.value

    if alert_data.operator is not None:
        alert.operator = alert_data.operator.value

    if alert_data.threshold_value is not None:
        alert.threshold_value = alert_data.threshold_value

    if alert_data.time_window_minutes is not None:
        alert.time_window_minutes = alert_data.time_window_minutes

    if alert_data.agent_ids is not None:
        alert.agent_ids = [str(aid) for aid in alert_data.agent_ids] if alert_data.agent_ids else None

    if alert_data.notify_frequency is not None:
        alert.notify_frequency = alert_data.notify_frequency.value

    if alert_data.notify_emails is not None:
        alert.notify_emails = alert_data.notify_emails

    if alert_data.notify_webhooks is not None:
        alert.notify_webhooks = alert_data.notify_webhooks

    if alert_data.status is not None:
        alert.status = alert_data.status.value

    db.commit()
    db.refresh(alert)

    return alert


@router.delete("/{alert_id}", status_code=204)
def delete_alert(
    alert_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Delete an alert."""
    alert = db.query(Alert).filter(
        and_(
            Alert.id == alert_id,
            Alert.organization_id == organization_id
        )
    ).first()

    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    db.delete(alert)
    db.commit()

    return None


@router.post("/{alert_id}/toggle", response_model=AlertResponse)
def toggle_alert_status(
    alert_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Toggle an alert's status between active and paused."""
    alert = db.query(Alert).filter(
        and_(
            Alert.id == alert_id,
            Alert.organization_id == organization_id
        )
    ).first()

    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    # Toggle between active and paused
    if alert.status == AlertStatus.ACTIVE.value:
        alert.status = AlertStatus.PAUSED.value
    else:
        alert.status = AlertStatus.ACTIVE.value

    db.commit()
    db.refresh(alert)

    return alert


# ============================================
# ALERT EVALUATION & NOTIFICATION ENDPOINTS
# ============================================


class TestNotificationRequest(BaseModel):
    """Schema for testing notifications."""
    webhook_url: Optional[str] = Field(None, description="Slack webhook URL to test")
    email: Optional[str] = Field(None, description="Email address to test")


class AlertEvaluationResponse(BaseModel):
    """Schema for alert evaluation response."""
    alert_id: str
    alert_name: str
    triggered: bool = False
    metric_value: Optional[float] = None
    threshold: Optional[float] = None
    operator: Optional[str] = None
    history_id: Optional[str] = None
    notifications_sent: Optional[int] = None
    notifications_successful: Optional[int] = None
    skipped_cooldown: Optional[bool] = None
    reason: Optional[str] = None
    error: Optional[str] = None


@router.post("/{alert_id}/trigger", response_model=AlertEvaluationResponse)
def trigger_alert_evaluation(
    alert_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """
    Manually trigger evaluation of a specific alert.
    Evaluates the alert condition right now and sends notifications if triggered.
    """
    alert = db.query(Alert).filter(
        and_(
            Alert.id == alert_id,
            Alert.organization_id == organization_id
        )
    ).first()

    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    result = alert_evaluation_service.evaluate_single_alert(alert, db)
    return result


@router.post("/evaluate/all")
def evaluate_all_alerts(
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """
    Evaluate all active alerts for the organization.
    Checks all alert conditions and triggers notifications for any that are breached.
    """
    # Get only this organization's active alerts
    active_alerts = db.query(Alert).filter(
        and_(
            Alert.organization_id == organization_id,
            Alert.status == AlertStatus.ACTIVE.value,
        )
    ).all()

    results = {
        "total_alerts": len(active_alerts),
        "triggered": 0,
        "not_triggered": 0,
        "errors": 0,
        "skipped_cooldown": 0,
        "details": [],
    }

    for alert in active_alerts:
        try:
            result = alert_evaluation_service.evaluate_single_alert(alert, db)
            results["details"].append(result)
            if result.get("triggered"):
                results["triggered"] += 1
            elif result.get("skipped_cooldown"):
                results["skipped_cooldown"] += 1
            else:
                results["not_triggered"] += 1
        except Exception as e:
            results["errors"] += 1
            results["details"].append({
                "alert_id": str(alert.id),
                "alert_name": alert.name,
                "error": str(e),
            })

    return results


@router.post("/{alert_id}/test-notification")
def test_alert_notification(
    alert_id: UUID,
    request: TestNotificationRequest,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """
    Send a test notification for an alert.
    Tests the notification channels without actually triggering the alert.
    """
    alert = db.query(Alert).filter(
        and_(
            Alert.id == alert_id,
            Alert.organization_id == organization_id
        )
    ).first()

    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    results = []
    now = datetime.utcnow()

    common_params = dict(
        alert_name=f"[TEST] {alert.name}",
        alert_description=alert.description or "This is a test notification",
        metric_type=alert.metric_type,
        aggregation=alert.aggregation,
        operator=alert.operator,
        threshold_value=alert.threshold_value,
        triggered_value=alert.threshold_value * 1.5,  # Simulate 150% of threshold
        time_window_minutes=alert.time_window_minutes,
        triggered_at=now,
        agent_names=None,
        alert_id=str(alert.id),
        history_id=None,
    )

    # Test specific webhook if provided, otherwise use alert's configured webhooks
    if request.webhook_url:
        result = alert_notification_service.send_slack_notification(
            webhook_url=request.webhook_url,
            **common_params,
        )
        results.append(result)
    elif alert.notify_webhooks:
        for webhook_url in alert.notify_webhooks:
            if webhook_url and webhook_url.strip():
                result = alert_notification_service.send_slack_notification(
                    webhook_url=webhook_url.strip(),
                    **common_params,
                )
                results.append(result)

    # Test specific email if provided, otherwise use alert's configured emails
    if request.email:
        result = alert_notification_service.send_email_notification(
            to_email=request.email,
            **common_params,
        )
        results.append(result)
    elif alert.notify_emails:
        for email_addr in alert.notify_emails:
            if email_addr and email_addr.strip():
                result = alert_notification_service.send_email_notification(
                    to_email=email_addr.strip(),
                    **common_params,
                )
                results.append(result)

    if not results:
        raise HTTPException(
            status_code=400,
            detail="No notification channels configured. Provide a webhook_url or email, "
                   "or configure notify_webhooks/notify_emails on the alert.",
        )

    return {
        "message": "Test notifications sent",
        "total": len(results),
        "successful": sum(1 for r in results if r.get("success")),
        "failed": sum(1 for r in results if not r.get("success")),
        "details": results,
    }


# ============================================
# ALERT HISTORY ENDPOINTS
# ============================================

@router.get("/history/all", response_model=List[AlertHistoryResponse])
def list_all_alert_history(
    alert_id: Optional[UUID] = None,
    status_filter: Optional[AlertHistoryStatus] = None,
    skip: int = 0,
    limit: int = 100,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """List alert history for all alerts in the organization."""
    query = db.query(AlertHistory).filter(AlertHistory.organization_id == organization_id)
    
    if alert_id:
        query = query.filter(AlertHistory.alert_id == alert_id)
    
    if status_filter:
        query = query.filter(AlertHistory.status == status_filter.value)
    
    history = query.order_by(AlertHistory.triggered_at.desc()).offset(skip).limit(limit).all()
    
    # Load related alert for each history entry
    for h in history:
        alert = db.query(Alert).filter(Alert.id == h.alert_id).first()
        if alert:
            h.alert = alert
    
    return history


@router.get("/{alert_id}/history", response_model=List[AlertHistoryResponse])
def list_alert_history(
    alert_id: UUID,
    status_filter: Optional[AlertHistoryStatus] = None,
    skip: int = 0,
    limit: int = 100,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """List history for a specific alert."""
    # Verify alert exists and belongs to organization
    alert = db.query(Alert).filter(
        and_(
            Alert.id == alert_id,
            Alert.organization_id == organization_id
        )
    ).first()

    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    query = db.query(AlertHistory).filter(AlertHistory.alert_id == alert_id)
    
    if status_filter:
        query = query.filter(AlertHistory.status == status_filter.value)
    
    history = query.order_by(AlertHistory.triggered_at.desc()).offset(skip).limit(limit).all()
    return history


@router.get("/history/{history_id}", response_model=AlertHistoryResponse)
def get_alert_history_item(
    history_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Get a specific alert history entry."""
    history = db.query(AlertHistory).filter(
        and_(
            AlertHistory.id == history_id,
            AlertHistory.organization_id == organization_id
        )
    ).first()

    if not history:
        raise HTTPException(status_code=404, detail="Alert history entry not found")

    # Load related alert
    alert = db.query(Alert).filter(Alert.id == history.alert_id).first()
    if alert:
        history.alert = alert

    return history


@router.put("/history/{history_id}", response_model=AlertHistoryResponse)
def update_alert_history(
    history_id: UUID,
    update_data: AlertHistoryUpdate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Update alert history (acknowledge or resolve)."""
    history = db.query(AlertHistory).filter(
        and_(
            AlertHistory.id == history_id,
            AlertHistory.organization_id == organization_id
        )
    ).first()

    if not history:
        raise HTTPException(status_code=404, detail="Alert history entry not found")

    # Handle status transitions
    if update_data.status is not None:
        new_status = update_data.status.value
        
        # Set timestamps based on status transition
        if new_status == AlertHistoryStatus.ACKNOWLEDGED.value and history.acknowledged_at is None:
            history.acknowledged_at = datetime.utcnow()
            if update_data.acknowledged_by:
                history.acknowledged_by = update_data.acknowledged_by
        
        if new_status == AlertHistoryStatus.RESOLVED.value and history.resolved_at is None:
            history.resolved_at = datetime.utcnow()
            if update_data.resolved_by:
                history.resolved_by = update_data.resolved_by
            if update_data.resolution_notes:
                history.resolution_notes = update_data.resolution_notes
        
        history.status = new_status

    db.commit()
    db.refresh(history)

    return history
