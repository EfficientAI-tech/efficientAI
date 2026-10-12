"""Per-organization alerting integration sync (opt-in, default off)."""

import secrets
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.models.database import Organization

DEFAULTS: Dict[str, Any] = {
    "sync_notification_lifecycle": False,
    "pagerduty_inbound_token": None,
    "pagerduty_webhook_signing_secret": None,
}

CONFIRM_PHRASE = "ENABLE_ALERT_SYNC"


def get_org_alerting_settings(organization_id: UUID, db: Session) -> Dict[str, Any]:
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    raw = dict((org.alerting_settings or {}) if org else {})
    merged = {**DEFAULTS, **{k: raw[k] for k in DEFAULTS if k in raw}}
    merged["sync_notification_lifecycle"] = bool(merged.get("sync_notification_lifecycle"))
    return merged


def is_lifecycle_sync_enabled(organization_id: UUID, db: Session) -> bool:
    return bool(get_org_alerting_settings(organization_id, db)["sync_notification_lifecycle"])


def _ensure_inbound_token(raw: Dict[str, Any]) -> str:
    token = raw.get("pagerduty_inbound_token")
    if token and str(token).strip():
        return str(token).strip()
    return secrets.token_urlsafe(32)


def build_pagerduty_webhook_url(inbound_token: str) -> Optional[str]:
    base = (settings.PUBLIC_BASE_URL or "").strip().rstrip("/")
    if not base or not inbound_token:
        return None
    prefix = (settings.API_V1_PREFIX or "/api/v1").rstrip("/")
    return f"{base}{prefix}/alerts/integrations/pagerduty/webhook/{inbound_token}"


def get_org_alerting_settings_for_api(organization_id: UUID, db: Session) -> Dict[str, Any]:
    merged = get_org_alerting_settings(organization_id, db)
    token = merged.get("pagerduty_inbound_token")
    has_secret = bool((merged.get("pagerduty_webhook_signing_secret") or "").strip())
    sync_on = bool(merged["sync_notification_lifecycle"])
    return {
        "sync_notification_lifecycle": sync_on,
        "pagerduty_webhook_url": build_pagerduty_webhook_url(token) if token else None,
        "has_pagerduty_webhook_signing_secret": has_secret,
        "pagerduty_inbound_ready": sync_on and has_secret,
        "confirmation_phrase_required": CONFIRM_PHRASE,
    }


def set_org_alerting_settings(
    organization_id: UUID,
    db: Session,
    *,
    sync_notification_lifecycle: bool,
    confirm_enable: bool = False,
    confirmation_phrase: Optional[str] = None,
    pagerduty_webhook_signing_secret: Optional[str] = None,
    clear_pagerduty_webhook_signing_secret: bool = False,
) -> Dict[str, Any]:
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    current = dict(org.alerting_settings or {})
    currently_on = bool(current.get("sync_notification_lifecycle"))

    if sync_notification_lifecycle and not currently_on:
        if not confirm_enable:
            raise HTTPException(
                status_code=400,
                detail="Enabling integration sync requires confirm_enable=true.",
            )
        if (confirmation_phrase or "").strip() != CONFIRM_PHRASE:
            raise HTTPException(
                status_code=400,
                detail=f"Type confirmation phrase exactly: {CONFIRM_PHRASE}",
            )
        current["pagerduty_inbound_token"] = _ensure_inbound_token(current)

    current["sync_notification_lifecycle"] = bool(sync_notification_lifecycle)

    if clear_pagerduty_webhook_signing_secret:
        current["pagerduty_webhook_signing_secret"] = None
    elif pagerduty_webhook_signing_secret is not None:
        secret = pagerduty_webhook_signing_secret.strip()
        current["pagerduty_webhook_signing_secret"] = secret or None

    org.alerting_settings = current
    db.commit()
    return get_org_alerting_settings_for_api(organization_id, db)


def resolve_org_by_pagerduty_token(db: Session, token: str) -> Optional[Organization]:
    if not token or not token.strip():
        return None
    token = token.strip()
    orgs = db.query(Organization).filter(Organization.alerting_settings.isnot(None)).all()
    for org in orgs:
        raw = org.alerting_settings or {}
        if str(raw.get("pagerduty_inbound_token") or "") == token:
            return org
    return None
