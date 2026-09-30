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
from app.services.telephony.plivo_client import normalize_e164

TWILIO_TRIAL_SMS_BODY_TEMPLATES = frozenset(
    {
        "sms_2fa",
        "sms_appointment_reminders",
        "sms_order_confirmation",
        "sms_delivery_updates",
        "sms_customer_support",
        "sms_marketing_promotions",
        "sms_event_notifications",
        "sms_account_alerts",
        "sms_feedback_surveys",
        "sms_internal_alerts",
    }
)


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


def _sms_outbound_body(cfg: dict[str, Any], user_text: str) -> str:
    template = _cfg_str(cfg, "twilio_sms_trial_body_template")
    if template:
        return template
    return user_text


def _normalize_sms_phone(value: str) -> str:
    try:
        return normalize_e164(value.strip())
    except ValueError:
        return value.strip()


def _twilio_api_error_detail(response: httpx.Response) -> str:
    try:
        data = response.json()
        if isinstance(data, dict):
            code = data.get("code")
            message = data.get("message")
            if code is not None or message:
                return f"Twilio {code}: {message}"
    except Exception:
        pass
    text = (response.text or "").strip()
    return text[:400] if text else f"HTTP {response.status_code}"


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
) -> str:
    if channel == "sms":
        to_addr = _normalize_sms_phone(to)
        from_line = _normalize_sms_phone(from_addr)
    else:
        to_addr = f"whatsapp:{to.lstrip('+')}"
        from_line = f"whatsapp:{from_addr.lstrip('+')}"
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            url,
            auth=(account_sid, auth_token),
            data={"From": from_line, "To": to_addr, "Body": body},
        )
        if resp.is_error:
            detail = _twilio_api_error_detail(resp)
            raise httpx.HTTPStatusError(
                detail,
                request=resp.request,
                response=resp,
            )
        try:
            data = resp.json()
            if isinstance(data, dict) and data.get("sid"):
                return str(data["sid"])
        except Exception:
            pass
        return ""


def test_twilio_sms_send(
    db: Session,
    *,
    organization_id: UUID,
    cfg: dict[str, Any],
    overrides: Optional[dict[str, str]] = None,
    telephony_phone_number_id: Optional[UUID] = None,
) -> dict[str, str]:
    """Send one Twilio SMS using stored credentials (connectivity / trial template check)."""
    channel = _cfg_str(cfg, "messaging_channel").lower() or "sms"
    if channel != "sms":
        raise ValueError("Agent messaging channel must be sms")

    merged = dict(cfg)
    if overrides:
        for key, val in overrides.items():
            if isinstance(val, str) and val.strip():
                merged[key] = val.strip()

    recipient = _cfg_str(merged, "messaging_recipient", "messaging_test_recipient")
    twilio_sid, twilio_token, twilio_from = _resolve_messaging_twilio_context(
        db,
        organization_id=organization_id,
        cfg=merged,
        telephony_phone_number_id=telephony_phone_number_id,
    )
    if overrides.get("twilio_from"):
        twilio_from = _normalize_sms_phone(overrides["twilio_from"])
    if not twilio_sid or not twilio_token:
        raise ValueError(
            "Twilio credentials are required — link a Twilio number under Telephony Numbers "
            "or save a Twilio telephony integration"
        )
    if not twilio_from or not recipient:
        raise ValueError("Twilio From number and eval recipient are required")

    body = _sms_outbound_body(merged, "EfficientAI test SMS")
    if body == "EfficientAI test SMS" and not _cfg_str(merged, "twilio_sms_trial_body_template"):
        raise ValueError(
            "Twilio trial accounts need Outbound SMS body (Twilio trial) set to a template name "
            "(e.g. sms_appointment_reminders)"
        )

    recipient_norm = _normalize_sms_phone(recipient)
    sid = _send_twilio_sms_with_trial_fallback(
        account_sid=twilio_sid,
        auth_token=twilio_token,
        from_addr=twilio_from,
        to=recipient_norm,
        body=body,
        cfg=merged,
    )
    return {
        "message_sid": sid,
        "to": recipient_norm,
        "from": _normalize_sms_phone(twilio_from),
        "body_sent": body,
    }


def _twilio_trial_fallback_body(cfg: dict[str, Any]) -> str:
    configured = _cfg_str(cfg, "twilio_sms_trial_body_template")
    if configured in TWILIO_TRIAL_SMS_BODY_TEMPLATES:
        return configured
    return "sms_appointment_reminders"


def _send_twilio_sms_with_trial_fallback(
    *,
    account_sid: str,
    auth_token: str,
    from_addr: str,
    to: str,
    body: str,
    cfg: dict[str, Any],
) -> str:
    try:
        return _send_twilio_message(
            account_sid=account_sid,
            auth_token=auth_token,
            from_addr=from_addr,
            to=to,
            body=body,
            channel="sms",
        )
    except httpx.HTTPStatusError as exc:
        detail = _twilio_api_error_detail(exc.response)
        if "572006" not in detail:
            raise
        fallback = _twilio_trial_fallback_body(cfg)
        if body == fallback:
            raise
        logger.info(
            "[MessagingChat] Twilio trial requires template Body; retrying with {}",
            fallback,
        )
        return _send_twilio_message(
            account_sid=account_sid,
            auth_token=auth_token,
            from_addr=from_addr,
            to=to,
            body=fallback,
            channel="sms",
        )


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


def _resolve_messaging_twilio_context(
    db: Session,
    *,
    organization_id: UUID,
    cfg: dict[str, Any],
    telephony_phone_number_id: Optional[UUID] = None,
) -> tuple[str, str, str]:
    """Return (account_sid, auth_token, from_e164) from inventory number or legacy config."""
    from app.models.database import TelephonyPhoneNumber

    tp_id = telephony_phone_number_id
    if not tp_id:
        raw = cfg.get("messaging_telephony_phone_number_id")
        if raw:
            try:
                tp_id = UUID(str(raw))
            except (TypeError, ValueError):
                tp_id = None
    if tp_id:
        number_row = (
            db.query(TelephonyPhoneNumber)
            .filter(
                TelephonyPhoneNumber.id == tp_id,
                TelephonyPhoneNumber.organization_id == organization_id,
                TelephonyPhoneNumber.is_active.is_(True),
            )
            .first()
        )
        if number_row:
            telephony = _resolve_telephony_integration(
                db,
                organization_id=organization_id,
                integration_id_raw=number_row.telephony_integration_id,
            )
            if telephony and telephony.provider.lower() == "twilio":
                sid = decrypt_api_key(telephony.auth_id)
                token = decrypt_api_key(telephony.auth_token)
                return sid, token, _normalize_sms_phone(number_row.phone_number)

    twilio_sid, twilio_token = _resolve_twilio_credentials(
        db, organization_id=organization_id, cfg=cfg
    )
    twilio_from = _cfg_str(cfg, "twilio_from", "twilio_whatsapp_from")
    return twilio_sid, twilio_token, twilio_from


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
    telephony_phone_number_id: Optional[UUID] = None,
    agent_id: Optional[UUID] = None,
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
    recipient = _normalize_sms_phone(recipient) if channel == "sms" else recipient
    outbound_body = _sms_outbound_body(cfg, user_text) if channel == "sms" else user_text

    sent_via = ""

    meta_token = _cfg_str(cfg, "meta_whatsapp_access_token", "whatsapp_access_token")
    meta_phone_id = _cfg_str(cfg, "meta_whatsapp_phone_number_id", "whatsapp_phone_number_id")
    twilio_sid, twilio_token, twilio_from = _resolve_messaging_twilio_context(
        db,
        organization_id=organization_id,
        cfg=cfg,
        telephony_phone_number_id=telephony_phone_number_id,
    )

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
                    agent_id=agent_id or organization_id,
                    twilio_from=_normalize_sms_phone(twilio_from),
                    messaging_recipient=recipient,
                )
                if not turn_id:
                    return None, "messaging_sms_concurrent_turn"
                _send_twilio_sms_with_trial_fallback(
                    account_sid=twilio_sid,
                    auth_token=twilio_token,
                    from_addr=twilio_from or sender,
                    to=recipient,
                    body=outbound_body,
                    cfg=cfg,
                )
            else:
                _send_twilio_message(
                    account_sid=twilio_sid,
                    auth_token=twilio_token,
                    from_addr=twilio_from or sender,
                    to=recipient,
                    body=outbound_body,
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
    except httpx.HTTPStatusError as exc:
        detail = str(exc) or _twilio_api_error_detail(exc.response)
        if "572006" in detail:
            detail = (
                f"{detail} — Twilio trial accounts require Body to be a template name "
                f"(e.g. sms_appointment_reminders). Set twilio_sms_trial_body_template on the agent."
            )
        logger.warning("[MessagingChat] outbound send failed: {}", detail)
        return None, f"messaging_send_failed:{detail}"
    except Exception as exc:
        logger.warning("[MessagingChat] outbound send failed: {}", exc)
        return None, f"messaging_send_failed:{exc}"

    reply = _fetch_sync_reply(cfg, transcript, channel)
    if reply:
        return reply.strip(), f"messaging_{sent_via}_sync"
    return None, f"messaging_{sent_via}_send_only"
