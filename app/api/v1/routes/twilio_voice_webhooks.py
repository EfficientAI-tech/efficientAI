"""Twilio voice webhooks (Media Streams)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from loguru import logger
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.services.agents.twilio_webhook_auth import (
    public_webhook_url_for_validation,
    validate_twilio_request,
)
from app.services.telephony.inbound_stream_answer import build_inbound_stream_answer_xml
from app.services.telephony.phone_routing import resolve_inbound_agent_for_number
from app.services.telephony.twilio_webhook_urls import twilio_webhook_base, twilio_voice_webhook_url
from app.api.v1.routes.twilio_sms_webhooks import _twilio_auth_token_for_integration

router = APIRouter(prefix="/telephony/twilio/webhooks", tags=["Twilio Voice Webhooks"])


async def _twilio_form_params(request: Request) -> dict[str, str]:
    form = await request.form()
    return {key: str(form.get(key) or "") for key in form.keys()}


@router.get("/voice-url")
async def twilio_voice_webhook_url_route() -> dict[str, str]:
    return {"url": twilio_voice_webhook_url()}


@router.post("/voice-inbound")
async def twilio_voice_inbound_webhook(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    params = await _twilio_form_params(request)
    to_number = params.get("To") or ""
    _, _, integration_id = resolve_inbound_agent_for_number(db, to_number)
    auth_token = _twilio_auth_token_for_integration(db, integration_id)
    if not auth_token:
        logger.warning("[TwilioVoice] missing credentials for To={}", to_number)
        return Response(
            content='<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>',
            media_type="text/xml",
            status_code=403,
        )
    signature = request.headers.get("X-Twilio-Signature") or ""
    public_base = twilio_webhook_base()
    signed_url = public_webhook_url_for_validation(str(request.url), public_base)
    ok = validate_twilio_request(
        auth_token=auth_token,
        url=signed_url,
        params=params,
        signature=signature,
    )
    if not ok and str(request.url) != signed_url:
        ok = validate_twilio_request(
            auth_token=auth_token,
            url=str(request.url),
            params=params,
            signature=signature,
        )
    if not ok:
        logger.warning("[TwilioVoice] invalid signature for To={}", to_number)
        return Response(
            content='<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>',
            media_type="text/xml",
            status_code=403,
        )

    xml = build_inbound_stream_answer_xml(db, params, provider_platform="twilio")
    return Response(content=xml, media_type="text/xml")
