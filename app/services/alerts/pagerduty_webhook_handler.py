"""PagerDuty v3 webhook → EfficientAI alert history (when org sync is enabled)."""

import hashlib
import hmac
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.models.database import Alert, AlertHistory
from app.models.enums import AlertHistoryStatus
from app.services.alerts.alerting_settings import (
    get_org_alerting_settings,
    is_lifecycle_sync_enabled,
)

_DEDUP_PREFIX = "efficientai-incident-"
_HISTORY_UUID_RE = re.compile(
    r"efficientai-incident-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.I,
)


def _history_id_from_dedup_key(dedup_key: Optional[str]) -> Optional[str]:
    if not dedup_key:
        return None
    if dedup_key.startswith(_DEDUP_PREFIX):
        return dedup_key[len(_DEDUP_PREFIX) :]
    match = _HISTORY_UUID_RE.search(dedup_key)
    return match.group(1) if match else None


def _extract_dedup_key(payload: Dict[str, Any]) -> Optional[str]:
    event = payload.get("event") or {}
    data = event.get("data") or {}
    for key in ("incident_key", "dedup_key"):
        if data.get(key):
            return str(data[key])
    if isinstance(data.get("body"), dict):
        body = data["body"]
        if body.get("incident_key"):
            return str(body["incident_key"])
    return None


def _agent_label(payload: Dict[str, Any]) -> str:
    event = payload.get("event") or {}
    agent = event.get("agent") or {}
    if agent.get("summary"):
        return str(agent["summary"])
    if agent.get("id"):
        return f"pagerduty:{agent['id']}"
    return "pagerduty"


def _signatures_from_header(signature_header: str) -> list[str]:
    sigs: list[str] = []
    for piece in signature_header.split(","):
        piece = piece.strip()
        if piece.startswith("v1="):
            sigs.append(piece[3:].strip())
    return sigs


def verify_pagerduty_signature(
    raw_body: bytes,
    signature_header: Optional[str],
    signing_secret: str,
    *,
    timestamp_header: Optional[str] = None,
) -> bool:
    secret = (signing_secret or "").strip()
    if not secret:
        return False
    if not signature_header:
        return False

    signatures = _signatures_from_header(signature_header)
    if not signatures:
        signatures = [signature_header.strip()]

    body_text = raw_body.decode("utf-8")
    ts = (timestamp_header or "").strip()

    for sig in signatures:
        if not sig:
            continue
        candidates: list[bytes] = []
        if ts:
            candidates.append(f"{ts}.{body_text}".encode("utf-8"))
        candidates.append(raw_body)
        for message in candidates:
            expected = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
            if hmac.compare_digest(expected, sig):
                return True
    return False


def apply_pagerduty_incident_event(
    organization_id: UUID,
    payload: Dict[str, Any],
    db: Session,
) -> Tuple[bool, str]:
    if not is_lifecycle_sync_enabled(organization_id, db):
        return False, "sync_disabled"

    event = payload.get("event") or {}
    event_type = str(event.get("event_type") or "")
    dedup_key = _extract_dedup_key(payload)
    history_id_str = _history_id_from_dedup_key(dedup_key)
    if not history_id_str:
        logger.warning("[PagerDutyWebhook] no history id in dedup_key={}", dedup_key)
        return False, "no_history_id"

    try:
        history_uuid = UUID(history_id_str)
    except ValueError:
        return False, "invalid_history_id"

    history = (
        db.query(AlertHistory)
        .filter(
            AlertHistory.id == history_uuid,
            AlertHistory.organization_id == organization_id,
        )
        .first()
    )
    if not history:
        return False, "history_not_found"

    actor = _agent_label(payload)
    now = datetime.now(timezone.utc)

    if event_type == "incident.acknowledged":
        if history.status == AlertHistoryStatus.RESOLVED.value:
            return True, "already_resolved"
        first_ack = history.status in (
            AlertHistoryStatus.TRIGGERED.value,
            AlertHistoryStatus.NOTIFIED.value,
        )
        if history.acknowledged_at is None:
            history.acknowledged_at = now
            history.acknowledged_by = actor
        if first_ack:
            history.status = AlertHistoryStatus.ACKNOWLEDGED.value
            _fanout_other_channels(db, history, phase="acknowledge", actor=actor)
        db.commit()
        return True, "acknowledged"

    if event_type in ("incident.resolved", "incident.status_update"):
        data = event.get("data") or {}
        status = str(data.get("status") or "").lower()
        if event_type == "incident.status_update" and status != "resolved":
            return True, "ignored_status"
        if (
            history.status == AlertHistoryStatus.RESOLVED.value
            or history.resolved_at is not None
        ):
            return True, "already_resolved"
        history.resolved_at = now
        history.resolved_by = actor
        if not history.resolution_notes:
            history.resolution_notes = "Resolved via PagerDuty."
        history.status = AlertHistoryStatus.RESOLVED.value
        alert = db.query(Alert).filter(Alert.id == history.alert_id).first()
        if alert:
            alert.suppress_reopen_until_ok = True
        _fanout_other_channels(db, history, phase="recovery", actor=actor)
        db.commit()
        return True, "resolved"

    return True, "ignored_event"


def _fanout_other_channels(
    db: Session,
    history: AlertHistory,
    *,
    phase: str,
    actor: Optional[str],
) -> None:
    """Tell Slack and email about a PagerDuty ack or resolve. Do not echo the action back."""
    from app.services.alerts.alert_notification_service import alert_notification_service

    alert = db.query(Alert).filter(Alert.id == history.alert_id).first()
    if not alert:
        return
    if phase == "acknowledge":
        results = alert_notification_service.send_acknowledge_notifications(
            alert,
            history_id=str(history.id),
            acknowledged_by=actor,
            include_pagerduty=False,
        )
    else:
        results = alert_notification_service.send_recovery_notifications(
            alert,
            history_id=str(history.id),
            include_pagerduty=False,
        )
    if not results:
        return
    details = dict(history.notification_details or {})
    lifecycle = dict(details.get("lifecycle") or {})
    lifecycle[phase] = results
    details["lifecycle"] = lifecycle
    history.notification_details = details
