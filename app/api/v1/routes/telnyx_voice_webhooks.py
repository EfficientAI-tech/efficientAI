"""Telnyx Call Control webhooks for inbound PSTN voice."""

from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from loguru import logger
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.models.database import TelephonyIntegration
from app.services.telephony.inbound_media_session import prepare_inbound_media_session
from app.services.telephony.phone_routing import resolve_inbound_agent_for_number
from app.services.telephony.telnyx_client import TelnyxClient
from app.services.telephony.telnyx_integration import (
    telnyx_api_key,
    telnyx_webhook_public_key,
)
from app.services.telephony.telnyx_webhook_auth import verify_telnyx_webhook_signature
from app.services.telephony.telnyx_webhook_urls import telnyx_voice_webhook_url

router = APIRouter(prefix="/telephony/telnyx/webhooks", tags=["Telnyx Voice Webhooks"])


def _event_payload(body: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        return "", {}
    event_type = str(data.get("event_type") or "").strip()
    payload = data.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    return event_type, payload


def _integration_for_inbound(
    db: Session,
    to_number: str,
) -> Optional[TelephonyIntegration]:
    agent_id, org_id, integration_id = resolve_inbound_agent_for_number(db, to_number)
    if not org_id or not integration_id:
        return None
    row = (
        db.query(TelephonyIntegration)
        .filter(
            TelephonyIntegration.id == integration_id,
            TelephonyIntegration.organization_id == org_id,
        )
        .first()
    )
    if row and (row.provider or "").lower() == "telnyx":
        return row
    return None


def _verify_request(
    request: Request,
    raw_body: bytes,
    integration: Optional[TelephonyIntegration],
) -> bool:
    public_key = telnyx_webhook_public_key(integration) if integration else ""
    if not public_key:
        return False
    return verify_telnyx_webhook_signature(
        public_key_b64=public_key,
        signature_b64=request.headers.get("telnyx-signature-ed25519") or "",
        timestamp=request.headers.get("telnyx-timestamp") or "",
        raw_body=raw_body,
    )


@router.get("/voice-url")
async def telnyx_voice_webhook_url_route() -> dict[str, str]:
    return {"url": telnyx_voice_webhook_url()}


@router.post("/voice")
async def telnyx_voice_webhook(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    raw_body = await request.body()
    try:
        body = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON")

    event_type, payload = _event_payload(body)
    to_number = payload.get("to") or payload.get("To") or ""
    integration = _integration_for_inbound(db, str(to_number)) if to_number else None

    if integration and not _verify_request(request, raw_body, integration):
        logger.warning("[TelnyxVoice] invalid webhook signature for to={}", to_number)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid Telnyx signature")

    if event_type != "call.initiated":
        return Response(status_code=status.HTTP_200_OK)

    direction = str(payload.get("direction") or "").lower()
    if direction and direction not in {"incoming", "inbound"}:
        return Response(status_code=status.HTTP_200_OK)

    call_control_id = str(payload.get("call_control_id") or "").strip()
    from_number = payload.get("from") or payload.get("From") or ""
    if not call_control_id or not to_number:
        return Response(status_code=status.HTTP_200_OK)

    params = {
        "to": to_number,
        "from": from_number,
        "call_control_id": call_control_id,
    }
    prepared = prepare_inbound_media_session(db, params, provider_platform="telnyx")
    if not prepared:
        logger.warning("[TelnyxVoice] no routing for inbound to={}", to_number)
        return Response(status_code=status.HTTP_200_OK)

    if not integration:
        integration = (
            db.query(TelephonyIntegration)
            .filter(TelephonyIntegration.id == prepared.telephony_integration_id)
            .first()
        )
    if not integration:
        logger.warning("[TelnyxVoice] missing integration for call {}", call_control_id)
        return Response(status_code=status.HTTP_200_OK)

    client = TelnyxClient(telnyx_api_key(integration))
    try:
        client.answer_call(call_control_id)
        client.streaming_start(call_control_id, prepared.ws_url)
    except Exception as exc:
        logger.warning("[TelnyxVoice] answer/stream failed for {}: {}", call_control_id, exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    logger.info(
        "[TelnyxVoice] streaming started call_control_id={} session={}",
        call_control_id,
        prepared.call_ref,
    )
    return Response(status_code=status.HTTP_200_OK)
