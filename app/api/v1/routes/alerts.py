"""Alerts routes."""

from fastapi import APIRouter, Depends, HTTPException, status
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
