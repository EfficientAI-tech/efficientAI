"""Meta WhatsApp Cloud: WABA subscription required for inbound message webhooks."""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

import httpx
from loguru import logger
from sqlalchemy.orm import Session

from app.models.database import TelephonyIntegration
from app.models.enums import TelephonyProvider


def _load_telephony_integration(
    db: Session,
    *,
    organization_id: UUID,
    integration_id_raw: Any,
) -> Optional[TelephonyIntegration]:
    if not integration_id_raw:
        return None
    try:
        integ_uuid = UUID(str(integration_id_raw))
    except (TypeError, ValueError):
        return None
    return (
        db.query(TelephonyIntegration)
        .filter(
            TelephonyIntegration.id == integ_uuid,
            TelephonyIntegration.organization_id == organization_id,
        )
        .first()
    )


def resolve_meta_whatsapp_waba_id(
    db: Session,
    *,
    organization_id: UUID,
    cfg: dict[str, Any],
) -> str:
    telephony_id = cfg.get("messaging_telephony_integration_id") or cfg.get(
        "messaging_integration_id"
    )
    telephony = _load_telephony_integration(
        db, organization_id=organization_id, integration_id_raw=telephony_id
    )
    if telephony and telephony.provider.lower() == TelephonyProvider.META_WHATSAPP.value:
        waba = (telephony.voice_app_id or "").strip()
        if waba:
            return waba
    raw = cfg.get("meta_whatsapp_waba_id") or cfg.get("whatsapp_business_account_id")
    return str(raw or "").strip()


def fetch_waba_subscribed_apps(waba_id: str, access_token: str) -> dict[str, Any]:
    url = f"https://graph.facebook.com/v21.0/{waba_id}/subscribed_apps"
    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, params={"access_token": access_token})
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {"data": payload}


def ensure_waba_subscribed_to_app(waba_id: str, access_token: str) -> bool:
    """POST subscribed_apps so Meta delivers whatsapp_business_account webhooks to this app."""
    waba = (waba_id or "").strip()
    token = (access_token or "").strip()
    if not waba or not token:
        return False
    url = f"https://graph.facebook.com/v21.0/{waba}/subscribed_apps"
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, params={"access_token": token})
            if response.status_code >= 400:
                body = (response.text or "")[:400]
                logger.warning(
                    "[MetaWhatsApp] subscribed_apps POST failed waba={} status={} body={}",
                    waba,
                    response.status_code,
                    body,
                )
                return False
            logger.info("[MetaWhatsApp] subscribed_apps OK for waba={}", waba)
            return True
    except httpx.HTTPError as exc:
        logger.warning("[MetaWhatsApp] subscribed_apps request failed waba={}: {}", waba, exc)
        return False


def ensure_meta_whatsapp_webhook_delivery(
    db: Session,
    *,
    organization_id: UUID,
    cfg: dict[str, Any],
    access_token: str,
) -> tuple[str, bool]:
    waba_id = resolve_meta_whatsapp_waba_id(db, organization_id=organization_id, cfg=cfg)
    if not waba_id:
        logger.warning(
            "[MetaWhatsApp] No WABA id on integration (voice_app_id) — "
            "real inbound message webhooks often never fire; set WABA 1531697088984781 on the integration"
        )
        return "", False
    ok = ensure_waba_subscribed_to_app(waba_id, access_token)
    logger.info(
        "[MetaWhatsApp] eval webhook prep waba={} subscribed_apps={}",
        waba_id,
        ok,
    )
    return waba_id, ok
