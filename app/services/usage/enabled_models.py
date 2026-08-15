"""Org- and credential-level enabled model allowlists."""

from __future__ import annotations

from typing import Iterable, List, Optional, Set
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.database import AIProvider, ModelProvider
from app.services.ai.model_config_service import ModelConfigService


def normalize_enabled_models(raw: Optional[Iterable[str]]) -> Optional[List[str]]:
    if raw is None:
        return None
    seen: set[str] = set()
    normalized: list[str] = []
    for item in raw:
        if item is None:
            continue
        name = str(item).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        normalized.append(name)
    return normalized or None


def catalog_models_for_provider(provider: str) -> List[str]:
    service = ModelConfigService()
    try:
        provider_enum = ModelProvider(provider.lower())
    except ValueError:
        return []
    options = service.get_model_options_by_provider(provider_enum)
    models: list[str] = []
    for key in ("llm", "stt", "tts", "s2s"):
        models.extend(options.get(key) or [])
    return sorted({m for m in models if m})


def effective_enabled_models_for_credential(credential: AIProvider) -> Optional[List[str]]:
    """Return explicit allowlist, or None meaning unrestricted (full provider catalog)."""
    return normalize_enabled_models(credential.enabled_models)


def filter_models_by_credential(
    credential: Optional[AIProvider],
    catalog_models: List[str],
) -> List[str]:
    if credential is None:
        return catalog_models
    allowlist = effective_enabled_models_for_credential(credential)
    if not allowlist:
        return catalog_models
    allowed = set(allowlist)
    filtered = [m for m in catalog_models if m in allowed]
    gateway = (credential.gateway_model or "").strip()
    if gateway and gateway not in filtered:
        filtered = [gateway, *filtered]
    return filtered


def _usage_models_for_org(db: Session, organization_id: UUID) -> Set[str]:
    rows = db.execute(
        text(
            """
            SELECT DISTINCT model
            FROM llm_usage_daily
            WHERE organization_id = CAST(:organization_id AS uuid)
              AND model IS NOT NULL
              AND model <> ''
            """
        ),
        {"organization_id": str(organization_id)},
    ).scalars().all()
    return {str(row).strip() for row in rows if row}


def _override_models_for_org(db: Session, organization_id: UUID) -> Set[str]:
    rows = db.execute(
        text(
            """
            SELECT DISTINCT model
            FROM org_model_pricing_overrides
            WHERE organization_id = CAST(:organization_id AS uuid)
            """
        ),
        {"organization_id": str(organization_id)},
    ).scalars().all()
    return {str(row).strip() for row in rows if row}


def org_pricing_eligible_models(db: Session, organization_id: UUID) -> List[str]:
    """Models org admins may set pricing overrides for."""
    models: set[str] = set()
    providers = (
        db.query(AIProvider)
        .filter(
            AIProvider.organization_id == organization_id,
            AIProvider.is_active.is_(True),
        )
        .all()
    )
    any_explicit_allowlist = False
    for provider in providers:
        gateway = (provider.gateway_model or "").strip()
        if gateway:
            models.add(gateway)
        allowlist = effective_enabled_models_for_credential(provider)
        if allowlist:
            any_explicit_allowlist = True
            models.update(allowlist)
        else:
            models.update(catalog_models_for_provider(provider.provider))

    if not any_explicit_allowlist and not models:
        for provider in providers:
            models.update(catalog_models_for_provider(provider.provider))

    models.update(_usage_models_for_org(db, organization_id))
    models.update(_override_models_for_org(db, organization_id))
    return sorted(models)


def org_union_enabled_models(db: Session, organization_id: UUID) -> List[str]:
    """All models enabled on any active integration credential."""
    return org_pricing_eligible_models(db, organization_id)
