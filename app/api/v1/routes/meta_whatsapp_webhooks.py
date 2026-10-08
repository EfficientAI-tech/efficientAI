"""Meta WhatsApp Cloud webhooks (chat eval inbound replies)."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from loguru import logger
from sqlalchemy.orm import Session

from app.config import settings
from app.dependencies import get_db, get_organization_id
from app.services.agents.chat_messaging_turn_wait import (
    complete_messaging_inbound_routed,
    complete_messaging_sms_turn,
)
from app.services.agents.meta_whatsapp_inbound import (
    iter_meta_whatsapp_text_messages,
    summarize_meta_whatsapp_webhook,
)
from app.services.telephony.meta_whatsapp_webhook_urls import meta_whatsapp_inbound_webhook_url
from app.services.telephony.meta_whatsapp_webhook_verify import verify_meta_whatsapp_signature
from app.services.telephony.phone_routing import resolve_meta_whatsapp_agent_for_inbound

router = APIRouter(prefix="/chat/messaging/meta", tags=["Meta WhatsApp Webhooks"])


def _verify_token() -> str:
    return (settings.META_WHATSAPP_WEBHOOK_VERIFY_TOKEN or "").strip()


@router.get("/whatsapp-inbound-url")
async def meta_whatsapp_inbound_webhook_url_route() -> dict[str, str]:
    return {"url": meta_whatsapp_inbound_webhook_url()}


@router.get("/webhook-delivery-check")
async def meta_whatsapp_webhook_delivery_check(
    db: Session = Depends(get_db),
    organization_id: UUID = Depends(get_organization_id),
) -> dict[str, str | bool | list]:
    """Check WABA subscribed_apps (required for Meta to POST inbound messages to your callback)."""
    from app.models.database import Agent
    from app.services.agents.chat_connection_config_store import chat_connection_config_for_runtime
    from app.services.agents.messaging_channel_chat import _resolve_messaging_meta_whatsapp_context
    from app.services.telephony.meta_whatsapp_webhook_setup import (
        fetch_waba_subscribed_apps,
        resolve_meta_whatsapp_waba_id,
    )
    agent = (
        db.query(Agent)
        .filter(
            Agent.organization_id == organization_id,
            Agent.call_medium == "chat",
        )
        .order_by(Agent.updated_at.desc())
        .first()
    )
    waba_id = ""
    token = ""
    if agent:
        cfg = chat_connection_config_for_runtime(agent.chat_connection_config)
        if (cfg.get("messaging_channel") or "").strip().lower() == "whatsapp":
            waba_id = resolve_meta_whatsapp_waba_id(
                db, organization_id=organization_id, cfg=cfg
            )
            _pid, token = _resolve_messaging_meta_whatsapp_context(
                db, organization_id=organization_id, cfg=cfg
            )

    subscribed: list = []
    ok = False
    error = ""
    if waba_id and token:
        try:
            payload = fetch_waba_subscribed_apps(waba_id, token)
            subscribed = payload.get("data") if isinstance(payload.get("data"), list) else []
            ok = bool(subscribed)
        except Exception as exc:
            error = str(exc)[:300]
    elif not waba_id:
        error = "Set WABA ID on your Meta WhatsApp telephony integration (voice_app_id field)."

    return {
        "callback_url": meta_whatsapp_inbound_webhook_url(),
        "verify_token_configured": bool(_verify_token()),
        "waba_id": waba_id,
        "waba_subscribed_apps": subscribed,
        "waba_subscribed": ok,
        "error": error,
    }


@router.get("/whatsapp-inbound")
async def meta_whatsapp_webhook_verify(
    hub_mode: str = Query("", alias="hub.mode"),
    hub_verify_token: str = Query("", alias="hub.verify_token"),
    hub_challenge: str = Query("", alias="hub.challenge"),
) -> Response:
    expected = _verify_token()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Meta WhatsApp webhook verify token is not configured",
        )
    if hub_mode == "subscribe" and hub_verify_token == expected:
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid verify token")


@router.post("/whatsapp-inbound")
async def meta_whatsapp_webhook_inbound(
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, str | int]:
    raw_body = await request.body()
    app_secret = (settings.META_WHATSAPP_APP_SECRET or "").strip()
    if not app_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Meta WhatsApp app secret is not configured (meta_whatsapp.app_secret)",
        )
    if not verify_meta_whatsapp_signature(
        raw_body,
        request.headers.get("X-Hub-Signature-256"),
        app_secret,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Meta webhook signature",
        )
    try:
        payload: dict[str, Any] = json.loads(raw_body) if raw_body else {}
    except Exception:
        payload = {}

    if payload:
        summary = summarize_meta_whatsapp_webhook(payload)
        logger.info(
            "[MetaWhatsAppWebhook] inbound POST object={} text_messages={} statuses={} phone_number_id={}",
            payload.get("object"),
            summary.get("text_messages"),
            summary.get("statuses"),
            summary.get("phone_number_id"),
        )

    matched = 0
    for phone_number_id, sender, body in iter_meta_whatsapp_text_messages(payload):
        logger.info(
            "[MetaWhatsAppWebhook] text from={} phone_number_id={} body_len={}",
            sender,
            phone_number_id,
            len(body),
        )
        agent = resolve_meta_whatsapp_agent_for_inbound(db, phone_number_id)
        ok = False
        if agent:
            ok = complete_messaging_sms_turn(
                agent_id=agent.id,
                line_to=phone_number_id,
                reply_from=sender,
                body=body,
            )
        if not ok:
            ok = complete_messaging_inbound_routed(
                line_to=phone_number_id,
                reply_from=sender,
                body=body,
            )
        if ok:
            matched += 1
            logger.info(
                "[MetaWhatsAppWebhook] completed eval turn agent={} phone_number_id={} from={}",
                getattr(agent, "id", None),
                phone_number_id,
                sender,
            )
        elif not agent:
            logger.warning(
                "[MetaWhatsAppWebhook] no agent and no pending turn for phone_number_id={} from={}",
                phone_number_id,
                sender,
            )

    return {"ok": "true", "matched": matched}
