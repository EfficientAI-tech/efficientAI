"""Outbound WhatsApp/SMS from workers for post-prod live chat eval."""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

import httpx
from loguru import logger
from sqlalchemy.orm import Session

from app.core.encryption import decrypt_api_key
from app.models.database import Integration, TelephonyIntegration
from app.services.agents.customer_api_chat import extract_reply_text


def _last_user_text(transcript: list[dict[str, str]]) -> str:
    for entry in reversed(transcript):
        if (entry.get("speaker") or "").strip() in ("Speaker 1", "user", "User"):
            text = (entry.get("text") or "").strip()
            if text:
                return text
    if transcript:
        return (transcript[-1].get("text") or "").strip()
    return ""


def _cfg_str(cfg: dict[str, Any], *keys: str) -> str:
    for key in keys:
        val = cfg.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _send_plivo_sms(
    integration: TelephonyIntegration,
    *,
    src: str,
    dst: str,
    body: str,
) -> None:
    from app.services.telephony.plivo_client import PlivoClient

    client = PlivoClient(
        decrypt_api_key(integration.auth_id),
        decrypt_api_key(integration.auth_token),
    )
    src_n = src.lstrip("+")
    dst_n = dst.lstrip("+")
    client.client.messages.create(src=src_n, dst=dst_n, text=body)


def _send_meta_whatsapp(
    *,
    phone_number_id: str,
    access_token: str,
    to: str,
    body: str,
) -> None:
    to_digits = to.lstrip("+").replace(" ", "")
    url = f"https://graph.facebook.com/v21.0/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to_digits,
        "type": "text",
        "text": {"body": body},
    }
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            json=payload,
        )
        resp.raise_for_status()


def _send_twilio_message(
    *,
    account_sid: str,
    auth_token: str,
    from_addr: str,
    to: str,
    body: str,
    channel: str,
) -> None:
    to_addr = to if channel == "sms" else f"whatsapp:{to.lstrip('+')}"
    from_line = from_addr if channel == "sms" else f"whatsapp:{from_addr.lstrip('+')}"
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            url,
            auth=(account_sid, auth_token),
            data={"From": from_line, "To": to_addr, "Body": body},
        )
        resp.raise_for_status()


def _fetch_sync_reply(cfg: dict[str, Any], transcript: list[dict[str, str]], channel: str) -> Optional[str]:
    sync_url = _cfg_str(cfg, "messaging_sync_reply_url", "sync_reply_url")
    if not sync_url:
        return None
    with httpx.Client(timeout=90.0) as client:
        resp = client.post(
            sync_url,
            json={
                "messages": transcript,
                "channel": channel,
                "sender_id": cfg.get("messaging_sender_id"),
            },
        )
        resp.raise_for_status()
        if resp.content:
            data = resp.json()
            return extract_reply_text(data) if isinstance(data, dict) else None
        return resp.text.strip() or None


def _resolve_telephony_integration(
    db: Session,
    *,
    organization_id: UUID,
    integration_id_raw: Any,
) -> Optional[TelephonyIntegration]:
    if not integration_id_raw:
        return None
    try:
        integration_uuid = UUID(str(integration_id_raw))
    except (TypeError, ValueError):
        return None
    return (
        db.query(TelephonyIntegration)
        .filter(
            TelephonyIntegration.id == integration_uuid,
            TelephonyIntegration.organization_id == organization_id,
            TelephonyIntegration.is_active == True,
        )
        .first()
    )


def _resolve_twilio_credentials(
    db: Session,
    *,
    organization_id: UUID,
    cfg: dict[str, Any],
) -> tuple[str, str]:
    telephony_id = cfg.get("messaging_telephony_integration_id") or cfg.get(
        "messaging_integration_id"
    )
    telephony = _resolve_telephony_integration(
        db, organization_id=organization_id, integration_id_raw=telephony_id
    )
    if telephony and telephony.provider.lower() == "twilio":
        sid = decrypt_api_key(telephony.auth_id)
        token = decrypt_api_key(telephony.auth_token)
        return sid, token
    sid = _cfg_str(cfg, "twilio_account_sid")
    token = _cfg_str(cfg, "twilio_auth_token")
    return sid, token


def try_messaging_worker_send(
    db: Session,
    *,
    organization_id: UUID,
    cfg: dict[str, Any],
    transcript: list[dict[str, str]],
) -> tuple[Optional[str], str]:
    """Send the latest user turn via carrier APIs; optional sync URL for agent reply."""
    channel = _cfg_str(cfg, "messaging_channel").lower() or "sms"
    recipient = _cfg_str(cfg, "messaging_recipient", "messaging_test_recipient")
    sender = _cfg_str(cfg, "messaging_sender_id", "messaging_from")
    user_text = _last_user_text(transcript)
    if not user_text:
        return None, "messaging_skip_no_user_text"
    if not recipient:
        return None, "messaging_skip_no_recipient"

    sent_via = ""

    meta_token = _cfg_str(cfg, "meta_whatsapp_access_token", "whatsapp_access_token")
    meta_phone_id = _cfg_str(cfg, "meta_whatsapp_phone_number_id", "whatsapp_phone_number_id")
    twilio_sid, twilio_token = _resolve_twilio_credentials(
        db, organization_id=organization_id, cfg=cfg
    )
    twilio_from = _cfg_str(cfg, "twilio_from", "twilio_whatsapp_from")

    plivo_integration_id = cfg.get("messaging_integration_id")
    telephony: Optional[TelephonyIntegration] = None
    if plivo_integration_id and not cfg.get("messaging_telephony_integration_id"):
        telephony = _resolve_telephony_integration(
            db,
            organization_id=organization_id,
            integration_id_raw=plivo_integration_id,
        )
        if telephony and telephony.provider.lower() != "plivo":
            telephony = None

    voice_integration_id = cfg.get("messaging_voice_integration_id")
    if not sender and voice_integration_id:
        try:
            vi = (
                db.query(Integration)
                .filter(
                    Integration.id == UUID(str(voice_integration_id)),
                    Integration.organization_id == organization_id,
                )
                .first()
            )
            if vi and vi.name:
                sender = vi.name
        except (TypeError, ValueError):
            pass

    try:
        if channel == "whatsapp" and meta_phone_id and meta_token:
            _send_meta_whatsapp(
                phone_number_id=meta_phone_id,
                access_token=meta_token,
                to=recipient,
                body=user_text,
            )
            sent_via = "meta_whatsapp"
        elif twilio_sid and twilio_token and twilio_from:
            turn_id = None
            if channel == "sms":
                from app.services.agents.chat_messaging_turn_wait import (
                    register_twilio_sms_turn,
                    wait_twilio_sms_reply,
                )

                turn_id = register_twilio_sms_turn(
                    twilio_from=twilio_from,
                    messaging_recipient=recipient,
                )
            _send_twilio_message(
                account_sid=twilio_sid,
                auth_token=twilio_token,
                from_addr=twilio_from or sender,
                to=recipient,
                body=user_text,
                channel=channel,
            )
            sent_via = f"twilio_{channel}"
            if channel == "sms" and turn_id:
                inbound = wait_twilio_sms_reply(turn_id)
                if inbound:
                    return inbound.strip(), f"messaging_{sent_via}_inbound"
        elif telephony and telephony.provider.lower() == "plivo" and sender:
            _send_plivo_sms(telephony, src=sender, dst=recipient, body=user_text)
            sent_via = "plivo_sms"
        else:
            return None, "messaging_skip_no_credentials"
    except Exception as exc:
        logger.warning("[MessagingChat] outbound send failed: {}", exc)
        return None, "messaging_send_failed"

    reply = _fetch_sync_reply(cfg, transcript, channel)
    if reply:
        return reply.strip(), f"messaging_{sent_via}_sync"
    return None, f"messaging_{sent_via}_send_only"
