"""Plivo webhook signature verification for multi-tenant deployments."""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from fastapi import HTTPException, Request, status
from loguru import logger
from sqlalchemy.orm import Session

from app.config import settings
from app.core.encryption import decrypt_api_key
from app.models.database import CallRecording, TelephonyIntegration, TelephonyPhoneNumber
from app.services.credentials.resolver import resolve_telephony_integration
from app.services.telephony.plivo_client import normalize_e164

WebhookKind = Literal["answer", "events", "masking"]


def build_plivo_webhook_uri(request: Request) -> str:
    """Build the callback URI Plivo used when signing the webhook."""
    configured_base = (settings.PLIVO_WEBHOOK_BASE_URL or "").strip().rstrip("/")
    if configured_base:
        uri = f"{configured_base}{request.url.path}"
        if request.url.query:
            uri = f"{uri}?{request.url.query}"
        return uri
    return str(request.url)


def _resolve_auth_token_for_phone(
    phone_number: Optional[str],
    db: Session,
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
            TelephonyIntegration.provider == "plivo",
        )
        .first()
    )
    if not integration:
        return None
    return decrypt_api_key(integration.auth_token)


def _resolve_auth_token_for_call_event(
    params: Dict[str, Any],
    db: Session,
) -> Optional[str]:
    call_uuid = (
        params.get("CallUUID")
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
        "plivo",
        db,
        recording.organization_id,
    )
    if not integration:
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

    try:
        from plivo.utils import validate_signature
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Plivo SDK is not installed",
        ) from exc

    uri = build_plivo_webhook_uri(request)
    if not validate_signature(auth_token, uri, params, signature):
        logger.warning(
            "Plivo webhook rejected: invalid signature for kind={} uri={}",
            webhook_kind,
            uri,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid webhook signature",
        )
