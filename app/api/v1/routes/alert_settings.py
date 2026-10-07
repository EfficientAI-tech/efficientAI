"""Org-level alerting integration sync (admin only)."""

import json
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth.rbac import require_admin
from app.dependencies import get_db, get_organization_id, require_enterprise_feature
from app.services.alerts.alerting_settings import (
    get_org_alerting_settings,
    get_org_alerting_settings_for_api,
    resolve_org_by_pagerduty_token,
    set_org_alerting_settings,
)
from app.services.alerts.pagerduty_webhook_handler import (
    apply_pagerduty_incident_event,
    verify_pagerduty_signature,
)

settings_router = APIRouter(
    prefix="/organizations/alerting-sync",
    tags=["Alerting"],
    dependencies=[
        Depends(require_enterprise_feature("alerts")),
    ],
)

webhook_router = APIRouter(prefix="/alerts/integrations/pagerduty", tags=["Alerting Webhooks"])


class AlertingSyncSettingsResponse(BaseModel):
    sync_notification_lifecycle: bool
    pagerduty_webhook_url: Optional[str] = None
    has_pagerduty_webhook_signing_secret: bool = False
    pagerduty_inbound_ready: bool = False
    confirmation_phrase_required: str


class AlertingSyncSettingsUpdate(BaseModel):
    sync_notification_lifecycle: bool = Field(
        description="When true, ack/resolve syncs across PagerDuty, Slack, and email."
    )
    confirm_enable: bool = Field(
        default=False,
        description="Required true when turning sync on.",
    )
    confirmation_phrase: Optional[str] = Field(
        default=None,
        description="Must match confirmation_phrase_required when enabling.",
    )
    pagerduty_webhook_signing_secret: Optional[str] = Field(
        default=None,
        description="Optional PagerDuty webhook signing secret for inbound verification.",
    )
    clear_pagerduty_webhook_signing_secret: bool = False


@settings_router.get("", response_model=AlertingSyncSettingsResponse)
def get_alerting_sync_settings(
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
    _admin: None = Depends(require_admin),
):
    return AlertingSyncSettingsResponse(**get_org_alerting_settings_for_api(organization_id, db))


@settings_router.put("", response_model=AlertingSyncSettingsResponse)
def update_alerting_sync_settings(
    body: AlertingSyncSettingsUpdate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
    _admin: None = Depends(require_admin),
):
    return AlertingSyncSettingsResponse(
        **set_org_alerting_settings(
            organization_id,
            db,
            sync_notification_lifecycle=body.sync_notification_lifecycle,
            confirm_enable=body.confirm_enable,
            confirmation_phrase=body.confirmation_phrase,
            pagerduty_webhook_signing_secret=body.pagerduty_webhook_signing_secret,
            clear_pagerduty_webhook_signing_secret=body.clear_pagerduty_webhook_signing_secret,
        )
    )


@webhook_router.post("/webhook/{inbound_token}", status_code=status.HTTP_200_OK)
async def pagerduty_inbound_webhook(
    inbound_token: str,
    request: Request,
    db: Session = Depends(get_db),
):
    org = resolve_org_by_pagerduty_token(db, inbound_token)
    if org is None:
        raise HTTPException(status_code=404, detail="Unknown webhook")

    raw = await request.body()
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    org_settings = get_org_alerting_settings(org.id, db)
    signing_secret = (org_settings.get("pagerduty_webhook_signing_secret") or "").strip()
    if not signing_secret:
        raise HTTPException(
            status_code=403,
            detail="PagerDuty signing secret is not configured for this organization",
        )
    sig_header = request.headers.get("X-PagerDuty-Signature")
    ts_header = request.headers.get("X-PagerDuty-Timestamp")
    if not verify_pagerduty_signature(
        raw,
        sig_header,
        signing_secret,
        timestamp_header=ts_header,
    ):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    ok, reason = apply_pagerduty_incident_event(org.id, payload, db)
    return {"ok": ok, "reason": reason}
