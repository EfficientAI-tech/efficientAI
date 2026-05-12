"""Credential resolution helpers shared by telephony, AI, and voice integrations.

Each helper returns a single row for ``(org, provider)`` using a consistent
priority: explicit ``credential_id`` -> ``is_default = TRUE`` -> most
recently updated active row. ``clear_other_defaults`` is used when promoting
a row so the partial unique index on ``is_default`` is never violated.
"""

from __future__ import annotations

from typing import Any, Optional, Type
from uuid import UUID

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.models.database import AIProvider, Integration, TelephonyIntegration


def _resolve_for_org_provider(
    model: Type[Any],
    *,
    db: Session,
    org_id: UUID,
    provider_field: str,
    provider_value: str,
    credential_id: Optional[UUID],
) -> Optional[Any]:
    base = db.query(model).filter(
        model.organization_id == org_id,
        model.is_active.is_(True),
    )

    if credential_id is not None:
        return base.filter(model.id == credential_id).first()

    column = getattr(model, provider_field)
    base = base.filter(func.lower(column) == provider_value.lower())

    default_row = base.filter(model.is_default.is_(True)).first()
    if default_row is not None:
        return default_row

    return base.order_by(
        desc(model.updated_at),
        desc(model.created_at),
    ).first()


def resolve_telephony_integration(
    provider: str,
    db: Session,
    org_id: UUID,
    credential_id: Optional[UUID] = None,
) -> Optional[TelephonyIntegration]:
    """Resolve one ``TelephonyIntegration`` row for ``(org, provider)``."""
    return _resolve_for_org_provider(
        TelephonyIntegration,
        db=db,
        org_id=org_id,
        provider_field="provider",
        provider_value=provider,
        credential_id=credential_id,
    )


def resolve_integration(
    platform: str,
    db: Session,
    org_id: UUID,
    credential_id: Optional[UUID] = None,
) -> Optional[Integration]:
    """Resolve one ``Integration`` row for ``(org, platform)``."""
    return _resolve_for_org_provider(
        Integration,
        db=db,
        org_id=org_id,
        provider_field="platform",
        provider_value=platform,
        credential_id=credential_id,
    )


def resolve_ai_provider(
    provider: str,
    db: Session,
    org_id: UUID,
    credential_id: Optional[UUID] = None,
) -> Optional[AIProvider]:
    """Resolve one ``AIProvider`` row for ``(org, provider)``."""
    return _resolve_for_org_provider(
        AIProvider,
        db=db,
        org_id=org_id,
        provider_field="provider",
        provider_value=provider,
        credential_id=credential_id,
    )


def clear_other_defaults(
    model: Type[Any],
    db: Session,
    org_id: UUID,
    *,
    keep_id: UUID,
    provider_field: str,
    provider_value: str,
) -> None:
    """Set ``is_default = FALSE`` on every other row for ``(org, provider)``.

    Caller is expected to flip the kept row's ``is_default`` to ``TRUE``
    afterwards (and commit). Using ``synchronize_session=False`` keeps the
    bulk update cheap; identity-mapped rows already loaded into the session
    will be refreshed on the next access.
    """
    column = getattr(model, provider_field)
    db.query(model).filter(
        model.organization_id == org_id,
        func.lower(column) == provider_value.lower(),
        model.id != keep_id,
        model.is_default.is_(True),
    ).update({"is_default": False}, synchronize_session=False)
