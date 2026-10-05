"""Platform Telnyx SMS webhooks (route by inventory phone number)."""

from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from loguru import logger
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.models.database import Agent, TelephonyIntegration
from app.services.agents.chat_messaging_turn_wait import complete_messaging_sms_turn
from app.services.telephony.phone_routing import resolve_messaging_sms_agent_for_inbound
from app.services.telephony.telnyx_integration import telnyx_webhook_public_key
from app.services.telephony.telnyx_webhook_auth import verify_telnyx_webhook_signature
from app.services.telephony.telnyx_webhook_urls import telnyx_sms_inbound_webhook_url

router = APIRouter(prefix="/telephony/telnyx/webhooks", tags=["Telnyx SMS Webhooks"])


def _public_key_for_integration(db: Session, integration_id) -> str:
    if not integration_id:
        return ""
    row = db.query(TelephonyIntegration).filter(TelephonyIntegration.id == integration_id).first()
    if not row or (row.provider or "").lower() != "telnyx":
        return ""
    return telnyx_webhook_public_key(row)


def _extract_inbound_sms(body: dict[str, Any]) -> tuple[str, str, str]:
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        return "", "", ""
    event_type = str(data.get("event_type") or "")
    if event_type != "message.received":
        return "", "", ""
    payload = data.get("payload")
    if not isinstance(payload, dict):
        return "", "", ""
    text = (payload.get("text") or "").strip()
    from_num = payload.get("from") or {}
    to_list = payload.get("to") or []
    from_e164 = ""
    if isinstance(from_num, dict):
        from_e164 = str(from_num.get("phone_number") or from_num.get("number") or "")
    elif isinstance(from_num, str):
        from_e164 = from_num
    to_e164 = ""
    if isinstance(to_list, list) and to_list:
        first = to_list[0]
        if isinstance(first, dict):
            to_e164 = str(first.get("phone_number") or first.get("number") or "")
        elif isinstance(first, str):
            to_e164 = first
    return text, from_e164, to_e164


def process_telnyx_sms_inbound(
    *,
    agent: Agent,
    body: dict[str, Any],
    public_key: str,
    request: Request,
    raw_body: bytes,
) -> None:
    if not public_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Telnyx webhook signature validation is not configured",
        )
    if not verify_telnyx_webhook_signature(
        public_key_b64=public_key,
        signature_b64=request.headers.get("telnyx-signature-ed25519") or "",
        timestamp=request.headers.get("telnyx-timestamp") or "",
        raw_body=raw_body,
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid Telnyx signature")

    text, msg_from, msg_to = _extract_inbound_sms(body)
    if not text:
        return

    logger.info("[TelnyxSMS] verified inbound from={} to={}", msg_from, msg_to)

    matched = complete_messaging_sms_turn(
        agent_id=agent.id,
        line_to=msg_to,
        reply_from=msg_from,
        body=text,
    )
    if matched:
        logger.info(
            "[TelnyxSMS] matched inbound for agent {} from {} to {}",
            agent.id,
            msg_from,
            msg_to,
        )
    else:
        logger.warning(
            "[TelnyxSMS] inbound did not match pending turn agent={} from={} to={}",
            agent.id,
            msg_from,
            msg_to,
        )


@router.get("/sms-inbound-url")
async def telnyx_sms_inbound_webhook_url_route() -> dict[str, str]:
    return {"url": telnyx_sms_inbound_webhook_url()}


@router.post("/sms-inbound")
async def telnyx_sms_inbound_platform_webhook(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    raw_body = await request.body()
    try:
        body = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON")

    _, msg_from, msg_to = _extract_inbound_sms(body)
    if not msg_to:
        return Response(status_code=status.HTTP_200_OK)

    agent, _number_row, integration_id = resolve_messaging_sms_agent_for_inbound(db, msg_to)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No messaging agent for this number")

    public_key = _public_key_for_integration(db, integration_id)
    process_telnyx_sms_inbound(
        agent=agent,
        body=body,
        public_key=public_key,
        request=request,
        raw_body=raw_body,
    )
    return Response(status_code=status.HTTP_200_OK)
