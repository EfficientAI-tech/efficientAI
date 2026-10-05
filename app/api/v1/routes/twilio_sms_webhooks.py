"""Platform Twilio SMS webhooks (route by inventory phone number, not per-agent token)."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from loguru import logger
from sqlalchemy.orm import Session

from app.services.telephony.twilio_webhook_urls import (
    twilio_sms_inbound_webhook_url,
    twilio_webhook_base,
)
from app.dependencies import get_db
from app.models.database import Agent, TelephonyIntegration
from app.services.agents.chat_connection_config_store import chat_connection_config_for_runtime
from app.services.agents.chat_messaging_turn_wait import complete_twilio_sms_turn
from app.services.agents.messaging_channel_chat import _resolve_twilio_credentials
from app.services.agents.twilio_webhook_auth import (
    public_webhook_url_for_validation,
    validate_twilio_request,
)
from app.services.telephony.phone_routing import resolve_messaging_sms_agent_for_inbound

router = APIRouter(prefix="/telephony/twilio/webhooks", tags=["Twilio SMS Webhooks"])


def _twilio_auth_token_for_integration(db: Session, integration_id) -> str:
    if not integration_id:
        return ""
    row = db.query(TelephonyIntegration).filter(TelephonyIntegration.id == integration_id).first()
    if not row or (row.provider or "").lower() != "twilio":
        return ""
    from app.core.encryption import decrypt_api_key

    return decrypt_api_key(row.auth_token)


async def _twilio_form_params(request: Request) -> dict[str, str]:
    form = await request.form()
    return {key: str(form.get(key) or "") for key in form.keys()}


def _validate_twilio_signature(
    *,
    request: Request,
    params: dict[str, str],
    auth_token: str,
) -> bool:
    signature = request.headers.get("X-Twilio-Signature") or ""
    if not auth_token or not signature:
        return False
    public_base = twilio_webhook_base()
    signed_url = public_webhook_url_for_validation(str(request.url), public_base)
    if validate_twilio_request(
        auth_token=auth_token,
        url=signed_url,
        params=params,
        signature=signature,
    ):
        return True
    alt_url = str(request.url)
    if alt_url != signed_url:
        return validate_twilio_request(
            auth_token=auth_token,
            url=alt_url,
            params=params,
            signature=signature,
        )
    return False


def process_twilio_sms_inbound(
    *,
    agent: Agent,
    params: dict[str, Any],
    auth_token: str,
    request: Request,
) -> None:
    if not auth_token:
        logger.warning("[TwilioWebhook] missing auth token for agent {}", agent.id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Twilio webhook signature validation is not configured",
        )
    signature_ok = _validate_twilio_signature(request=request, params=params, auth_token=auth_token)
    if not signature_ok:
        logger.warning("[TwilioWebhook] invalid signature for agent {}", agent.id)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid Twilio signature")

    body = (params.get("Body") or "").strip()
    msg_from = params.get("From") or ""
    msg_to = params.get("To") or ""
    if not body:
        return

    matched = complete_twilio_sms_turn(
        agent_id=agent.id,
        twilio_to=msg_to,
        reply_from=msg_from,
        body=body,
    )
    if matched:
        logger.info(
            "[TwilioWebhook] matched inbound SMS for agent {} from {} to {}",
            agent.id,
            msg_from,
            msg_to,
        )
    else:
        logger.warning(
            "[TwilioWebhook] inbound SMS for agent {} did not match a pending eval turn "
            "(from={}, to={}). Check recipient/From numbers and run eval before replying.",
            agent.id,
            msg_from,
            msg_to,
        )


@router.get("/sms-inbound-url")
async def twilio_sms_inbound_webhook_url_route() -> dict[str, str]:
    return {"url": twilio_sms_inbound_webhook_url()}


@router.post("/sms-inbound")
async def twilio_sms_inbound_platform_webhook(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    params = await _twilio_form_params(request)
    msg_from = params.get("From") or ""
    msg_to = params.get("To") or ""
    body_preview = (params.get("Body") or "").strip()[:80]
    logger.info(
        "[TwilioWebhook] platform inbound POST from={} to={} body={!r}",
        msg_from,
        msg_to,
        body_preview,
    )

    agent, number_row, integration_id = resolve_messaging_sms_agent_for_inbound(db, msg_to)
    if not agent or not number_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No messaging agent for this number")

    auth_token = _twilio_auth_token_for_integration(db, integration_id)
    if not auth_token:
        cfg = chat_connection_config_for_runtime(agent.chat_connection_config)
        _, auth_token = _resolve_twilio_credentials(
            db,
            organization_id=agent.organization_id,
            cfg=cfg,
        )

    process_twilio_sms_inbound(agent=agent, params=params, auth_token=auth_token, request=request)

    return Response(
        content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
        media_type="text/xml",
    )
