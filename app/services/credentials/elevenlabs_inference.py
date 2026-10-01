"""Resolve ElevenLabs residency API base URL for TTS/STT inference."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import ModelProvider, VoiceBundle
from app.services.credentials.resolver import resolve_integration


def resolve_elevenlabs_api_base_url(
    db: Session,
    organization_id: UUID,
    *,
    credential_id: Optional[UUID] = None,
) -> Optional[str]:
    """Return stored integration ``api_base_url`` for ElevenLabs (or None for global)."""
    integration = resolve_integration(
        "elevenlabs",
        db,
        organization_id,
        credential_id=credential_id,
    )
    if not integration:
        return None
    return getattr(integration, "api_base_url", None)


def resolve_elevenlabs_api_base_url_for_provider(
    db: Session,
    organization_id: UUID,
    provider: ModelProvider,
    *,
    credential_id: Optional[UUID] = None,
) -> Optional[str]:
    provider_value = (
        provider.value if hasattr(provider, "value") else str(provider)
    ).lower()
    if provider_value != ModelProvider.ELEVENLABS.value:
        return None
    return resolve_elevenlabs_api_base_url(
        db,
        organization_id,
        credential_id=credential_id,
    )


def resolve_elevenlabs_api_base_url_for_voice_bundle_leg(
    db: Session,
    organization_id: UUID,
    voice_bundle: Optional[VoiceBundle],
    leg: str,
) -> Optional[str]:
    """Resolve residency URL for STT or TTS leg on a voice bundle."""
    if not voice_bundle:
        return None
    provider = getattr(voice_bundle, f"{leg}_provider", None)
    if not provider:
        return None
    provider_value = (
        provider.value if hasattr(provider, "value") else str(provider)
    ).lower()
    if provider_value != ModelProvider.ELEVENLABS.value:
        return None
    credential_id = getattr(voice_bundle, f"{leg}_credential_id", None)
    return resolve_elevenlabs_api_base_url(
        db,
        organization_id,
        credential_id=credential_id,
    )
