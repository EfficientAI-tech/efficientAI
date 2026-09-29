"""Public webhooks for chat messaging integrations (Twilio SMS inbound)."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from loguru import logger
from sqlalchemy.orm import Session

from app.core.public_url import configured_public_base_url
from app.dependencies import get_db
from app.models.database import Agent
from app.services.agents.chat_connection_config_store import chat_connection_config_for_runtime
from app.services.agents.chat_messaging_turn_wait import complete_twilio_sms_turn
from app.services.agents.messaging_channel_chat import _resolve_twilio_credentials
from app.services.agents.twilio_webhook_auth import (
    public_webhook_url_for_validation,
    validate_twilio_request,
)

router = APIRouter(prefix="/chat/messaging", tags=["Chat Messaging Webhooks"])


def _agent_for_webhook_token(db: Session, token: str) -> Optional[Agent]:
    token = (token or "").strip()
    if not token:
        return None
    return (
        db.query(Agent)
        .filter(Agent.chat_connection_config["twilio_inbound_webhook_token"].astext == token)
        .first()
    )


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

    form = await request.form()
    params = {key: str(form.get(key) or "") for key in form.keys()}
    cfg = chat_connection_config_for_runtime(agent.chat_connection_config)
    auth_token = _twilio_auth_token_for_agent(db, agent, cfg)
    signature = request.headers.get("X-Twilio-Signature") or ""
    public_base = configured_public_base_url()
    signed_url = public_webhook_url_for_validation(str(request.url), public_base)
    if auth_token and not validate_twilio_request(
        auth_token=auth_token,
        url=signed_url,
        params=params,
        signature=signature,
    ):
        logger.warning("[TwilioWebhook] invalid signature for agent {}", agent.id)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid Twilio signature")

    body = (params.get("Body") or "").strip()
    msg_from = params.get("From") or ""
    msg_to = params.get("To") or ""
    if body:
        complete_twilio_sms_turn(
            twilio_to=msg_to,
            reply_from=msg_from,
            body=body,
        )

    return Response(content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>', media_type="text/xml")
