"""Choose the carrier media serializer and hangup credentials."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.config import settings
from app.core.encryption import decrypt_api_key
from app.services.credentials.resolver import resolve_telephony_integration
from efficientai.serializers.plivo import PlivoFrameSerializer
from efficientai.serializers.vobiz import VobizFrameSerializer


def _plivo_call_control_credentials(
    db: Session,
    organization_id: UUID,
    *,
    telephony_integration_id: Optional[UUID] = None,
) -> tuple[str, str]:
    integration = resolve_telephony_integration(
        "plivo",
        db,
        organization_id,
        credential_id=telephony_integration_id,
    )
    if integration:
        return (
            decrypt_api_key(integration.auth_id).strip(),
            decrypt_api_key(integration.auth_token).strip(),
        )
    return (settings.PLIVO_AUTH_ID or "").strip(), (settings.PLIVO_AUTH_TOKEN or "").strip()


def telephony_integration_id_from_call_row(call_row) -> Optional[UUID]:
    if call_row is None:
        return None
    data = call_row.call_data if isinstance(call_row.call_data, dict) else {}
    raw = data.get("telephony_integration_id")
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except (TypeError, ValueError):
        return None


def build_carrier_frame_serializer(
    *,
    provider_platform: Optional[str],
    stream_id: str,
    call_id: Optional[str],
    organization_id: UUID,
    db: Session,
    telephony_integration_id: Optional[UUID] = None,
):
    """Return the media serializer whose hangup API matches the live carrier."""
    platform = (provider_platform or "").strip().lower()
    if platform == "plivo":
        auth_id, auth_token = _plivo_call_control_credentials(
            db,
            organization_id,
            telephony_integration_id=telephony_integration_id,
        )
        return PlivoFrameSerializer(
            stream_id=stream_id,
            call_id=call_id,
            auth_id=auth_id,
            auth_token=auth_token,
            params=PlivoFrameSerializer.InputParams(sample_rate=8000),
        )

    return VobizFrameSerializer(
        stream_id=stream_id,
        call_id=call_id,
        auth_id=settings.VOBIZ_AUTH_ID,
        auth_token=settings.VOBIZ_AUTH_TOKEN,
        params=VobizFrameSerializer.InputParams(
            sample_rate=8000,
            api_base=settings.VOBIZ_API_BASE,
        ),
    )
