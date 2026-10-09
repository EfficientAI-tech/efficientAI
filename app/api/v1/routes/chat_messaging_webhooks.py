"""Public webhooks for chat messaging integrations (Twilio SMS inbound)."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from loguru import logger
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.core.public_url import configured_public_base_url
from app.services.telephony.meta_whatsapp_webhook_urls import meta_whatsapp_inbound_webhook_url
from app.services.telephony.telnyx_webhook_urls import telnyx_webhook_base
from app.services.telephony.twilio_webhook_urls import twilio_webhook_base
from app.models.database import Agent
from app.services.agents.chat_connection_config_store import chat_connection_config_for_runtime
from app.services.agents.messaging_channel_chat import _resolve_twilio_credentials
from app.api.v1.routes.twilio_sms_webhooks import (
    _twilio_form_params,
    process_twilio_sms_inbound,
)

router = APIRouter(prefix="/chat/messaging", tags=["Chat Messaging Webhooks"])


def _webhook_base_or_public(getter) -> str:
    try:
        return getter()
    except ValueError:
        return configured_public_base_url()


@router.get("/public-base-url")
async def messaging_public_base_url() -> dict[str, str]:
    """Public API bases for messaging webhook URLs (per provider config, then security.public_base_url)."""
    twilio_base = _webhook_base_or_public(twilio_webhook_base)
    telnyx_base = _webhook_base_or_public(telnyx_webhook_base)
    try:
        meta_whatsapp_url = meta_whatsapp_inbound_webhook_url()
    except ValueError:
        meta_whatsapp_url = ""
    return {
        "public_base_url": twilio_base,
        "twilio_public_base_url": twilio_base,
        "telnyx_public_base_url": telnyx_base,
        "meta_whatsapp_inbound_webhook_url": meta_whatsapp_url,
    }


def _agent_for_webhook_token(db: Session, token: str) -> Optional[Agent]:
    token = (token or "").strip()
    if not token:
        return None
    token_expr = Agent.chat_connection_config.op("->>")("twilio_inbound_webhook_token")
    return db.query(Agent).filter(token_expr == token).first()


def _twilio_auth_token_for_agent(db: Session, agent: Agent, cfg: dict[str, Any]) -> str:
    _, token = _resolve_twilio_credentials(
        db,
        organization_id=agent.organization_id,
        cfg=cfg,
    )
    return token


@router.post("/twilio/inbound/{webhook_token}")
async def twilio_sms_inbound_webhook(
    webhook_token: str,
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    agent = _agent_for_webhook_token(db, webhook_token)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown webhook")

    params = await _twilio_form_params(request)
    msg_from = params.get("From") or ""
    msg_to = params.get("To") or ""
    body_preview = (params.get("Body") or "").strip()[:80]
    logger.info(
        "[TwilioWebhook] legacy token inbound POST agent={} from={} to={} body={!r}",
        agent.id,
        msg_from,
        msg_to,
        body_preview,
    )

    cfg = chat_connection_config_for_runtime(agent.chat_connection_config)
    auth_token = _twilio_auth_token_for_agent(db, agent, cfg)
    process_twilio_sms_inbound(agent=agent, params=params, auth_token=auth_token, request=request)

    return Response(content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>', media_type="text/xml")
