"""Plivo webhook signature verification for multi-tenant deployments."""

from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Any, Dict, Literal, Optional
from uuid import UUID

from fastapi import HTTPException, Request, status
from loguru import logger
from sqlalchemy.orm import Session

from app.config import settings
from app.core.encryption import decrypt_api_key
from app.models.database import CallRecording, TelephonyIntegration, TelephonyPhoneNumber
from app.services.credentials.resolver import resolve_telephony_integration
from app.services.telephony.plivo_client import normalize_e164
from app.services.telephony.webhook_signature_v1 import (
    compute_plivo_v1_webhook_signature,
    validate_plivo_v1_webhook_signature,
)

WebhookKind = Literal["answer", "events", "masking"]
VobizWebhookKind = Literal["answer", "events", "recording"]


def signature_params_from_request(request: Request, payload: Dict[str, Any]) -> Dict[str, str]:
    """POST body fields used for V1 signing (exclude query-string keys duplicated in payload)."""
    query_keys = set(request.query_params.keys())
    return {k: str(v) for k, v in payload.items() if k not in query_keys}


def build_plivo_webhook_uri(request: Request) -> str:
    """Build the callback URI Plivo used when signing the webhook."""
    configured_base = (settings.PLIVO_WEBHOOK_BASE_URL or "").strip().rstrip("/")
    if configured_base:
        uri = f"{configured_base}{request.url.path}"
        if request.url.query:
            uri = f"{uri}?{request.url.query}"
        return uri
    return str(request.url)


def build_vobiz_webhook_uri(request: Request) -> str:
    """Build the callback URI Vobiz used when signing the webhook."""
    configured_base = (
        settings.VOBIZ_WEBHOOK_BASE_URL or settings.PLIVO_WEBHOOK_BASE_URL or ""
    ).strip().rstrip("/")
    if configured_base:
        uri = f"{configured_base}{request.url.path}"
        if request.url.query:
            uri = f"{uri}?{request.url.query}"
        return uri
    return str(request.url)


def _resolve_auth_token_for_phone(
    phone_number: Optional[str],
    db: Session,
    *,
    provider: str = "plivo",
) -> Optional[str]:
    if not phone_number:
        return None
    try:
        normalized = normalize_e164(phone_number)
    except ValueError:
        return None

    number = (
        db.query(TelephonyPhoneNumber)
        .filter(
            TelephonyPhoneNumber.phone_number == normalized,
            TelephonyPhoneNumber.is_active.is_(True),
        )
        .first()
    )
    if not number:
        return None

    integration = (
        db.query(TelephonyIntegration)
        .filter(
            TelephonyIntegration.id == number.telephony_integration_id,
            TelephonyIntegration.is_active.is_(True),
            TelephonyIntegration.provider == provider,
        )
        .first()
    )
    if integration:
        return decrypt_api_key(integration.auth_token).strip().strip()

    if provider == "vobiz":
        return _platform_vobiz_auth_token()
    return None


def _platform_vobiz_auth_token() -> Optional[str]:
    token = (settings.VOBIZ_AUTH_TOKEN or "").strip()
    return token or None


def _auth_token_for_vobiz_org(db: Session, org_id: UUID) -> Optional[str]:
    integration = resolve_telephony_integration("vobiz", db, org_id)
    if integration:
        return decrypt_api_key(integration.auth_token).strip()
    return _platform_vobiz_auth_token()


def _resolve_auth_token_for_call_event(
    params: Dict[str, Any],
    db: Session,
    *,
    provider: str = "plivo",
) -> Optional[str]:
    call_uuid = (
        params.get("CallUUID")
        or params.get("call_uuid")
        or params.get("RequestUUID")
        or params.get("CallSid")
        or params.get("call_sid")
        or params.get("Sid")
    )
    if not call_uuid:
        return None

    recording = (
        db.query(CallRecording)
        .filter(CallRecording.provider_call_id == call_uuid)
        .first()
    )
    if not recording:
        return None

    integration = resolve_telephony_integration(
        provider,
        db,
        recording.organization_id,
    )
    if not integration:
        if provider == "vobiz":
            return _auth_token_for_vobiz_org(db, recording.organization_id)
        return None
    return decrypt_api_key(integration.auth_token)


def resolve_plivo_auth_token(
    webhook_kind: WebhookKind,
    params: Dict[str, Any],
    db: Session,
) -> Optional[str]:
    if webhook_kind in {"answer", "masking"}:
        phone_number = params.get("To") or params.get("to")
        return _resolve_auth_token_for_phone(phone_number, db)
    if webhook_kind == "events":
        return _resolve_auth_token_for_call_event(params, db)
    return None


def verify_plivo_webhook(
    request: Request,
    params: Dict[str, Any],
    webhook_kind: WebhookKind,
    db: Session,
) -> None:
    """Validate X-Plivo-Signature before processing webhook params."""
    signature = request.headers.get("X-Plivo-Signature")
    if not signature:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing webhook signature",
        )

    auth_token = resolve_plivo_auth_token(webhook_kind, params, db)
    if not auth_token:
        logger.warning(
            "Plivo webhook rejected: unable to resolve auth token for kind={}",
            webhook_kind,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid webhook signature",
        )

    uri = build_plivo_webhook_uri(request)
    sign_params = signature_params_from_request(request, params)
    if not validate_plivo_v1_webhook_signature(auth_token, uri, sign_params, signature):
        logger.warning(
            "Plivo webhook rejected: invalid signature for kind={} uri={}",
            webhook_kind,
            uri,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid webhook signature",
        )


def resolve_vobiz_auth_token(
    webhook_kind: VobizWebhookKind,
    params: Dict[str, Any],
    db: Session,
    *,
    call_ref: Optional[str] = None,
) -> Optional[str]:
    if call_ref:
        from app.services.telephony.call_recording_lifecycle import find_call_recording
        from app.services.telephony.vobiz_session import get_call_session

        session = get_call_session(call_ref)
        if session and session.organization_id:
            return _auth_token_for_vobiz_org(db, UUID(session.organization_id))
        row = find_call_recording(db, call_ref=call_ref, provider_call_id=None)
        if row:
            return _auth_token_for_vobiz_org(db, row.organization_id)

    if webhook_kind == "answer":
        phone_number = params.get("To") or params.get("to") or params.get("From") or params.get("from")
        return _resolve_auth_token_for_phone(phone_number, db, provider="vobiz")
    if webhook_kind in {"events", "recording"}:
        return _resolve_auth_token_for_call_event(params, db, provider="vobiz")
    return None


def verify_vobiz_webhook(
    request: Request,
    params: Dict[str, Any],
    webhook_kind: VobizWebhookKind,
    db: Session,
    *,
    call_ref: Optional[str] = None,
) -> None:
    """Validate Vobiz (Plivo-compatible) webhook signature before processing."""
    from app.config import settings

    if not settings.VOBIZ_WEBHOOK_VERIFY:
        logger.warning("Vobiz webhook signature verification is disabled (VOBIZ_WEBHOOK_VERIFY=false)")
        return

    signature = request.headers.get("X-Plivo-Signature") or request.headers.get("X-Vobiz-Signature")
    if not signature:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing webhook signature",
        )

    auth_token = resolve_vobiz_auth_token(
        webhook_kind,
        params,
        db,
        call_ref=call_ref,
    )
    if not auth_token:
        logger.warning(
            "Vobiz webhook rejected: unable to resolve auth token for kind={}",
            webhook_kind,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid webhook signature",
        )

    uri = build_vobiz_webhook_uri(request)
    sign_params = signature_params_from_request(request, params)
    if not validate_plivo_v1_webhook_signature(auth_token, uri, sign_params, signature):
        expected = compute_plivo_v1_webhook_signature(auth_token, uri, sign_params)
        logger.warning(
            "Vobiz webhook rejected: invalid signature for kind={} uri={} sign_param_keys={} "
            "(sign with the Vobiz auth_token for the To number's telephony integration, "
            "or platform VOBIZ_AUTH_TOKEN if the number uses the platform account; "
            "quote + in shell: --param 'To=+91...')",
            webhook_kind,
            uri,
            sorted(sign_params.keys()),
        )
        if settings.DEBUG:
            logger.debug(
                "Vobiz webhook signature debug: expected={} received={}",
                expected,
                (signature or "").strip(),
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid webhook signature",
        )
