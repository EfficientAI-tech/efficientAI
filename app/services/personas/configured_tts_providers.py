"""Resolve TTS provider keys configured for an organization."""

from __future__ import annotations

from typing import Set
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import AIProvider, Integration
from app.models.enums import ModelProvider
from app.services.ai.model_config_service import model_config_service


def _tts_capable_provider_keys() -> Set[str]:
    keys: Set[str] = set()
    for provider_enum in ModelProvider:
        try:
            tts_models = model_config_service.get_models_by_type(provider_enum, "tts")
        except Exception:
            tts_models = []
        if tts_models:
            keys.add(provider_enum.value)
    return keys


def get_configured_tts_provider_keys(organization_id: UUID, db: Session) -> Set[str]:
    """Return provider keys with active credentials and TTS capability."""
    tts_capable = _tts_capable_provider_keys()
    active_keys: Set[str] = set()

    ai_providers = (
        db.query(AIProvider)
        .filter(
            AIProvider.organization_id == organization_id,
            AIProvider.is_active == True,  # noqa: E712
        )
        .all()
    )
    for ap in ai_providers:
        pval = (ap.provider or "").lower()
        if pval in tts_capable:
            active_keys.add(pval)

    integrations = (
        db.query(Integration)
        .filter(
            Integration.organization_id == organization_id,
            Integration.is_active == True,  # noqa: E712
        )
        .all()
    )
    for integ in integrations:
        pval = (integ.platform or "").lower()
        if pval in tts_capable:
            active_keys.add(pval)

    return active_keys
