"""Shared credential resolution for AIProvider / Integration / TelephonyIntegration.

Now that an organization can hold multiple API keys for the same provider,
runtime callers (LLM service, transcription service, telephony service,
WebRTC bridge, etc.) need a single, consistent place to pick which row to
use. This module centralises that logic:

    1. If an explicit ``credential_id`` is given, look up exactly that row.
    2. Otherwise prefer the row with ``is_default = TRUE``.
    3. Otherwise (back-compat for orgs that haven't been migrated yet) fall
       back to the most recently updated active row.
"""

from __future__ import annotations

from typing import Optional, Type, TypeVar, Union
from uuid import UUID

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.models.database import (
    AIProvider,
    Integration,
    ModelProvider,
    TelephonyIntegration,
)


AIProviderCredential = AIProvider
IntegrationCredential = Integration
TelephonyCredential = TelephonyIntegration


T = TypeVar("T")


def _to_str(provider: Union[str, ModelProvider, None]) -> Optional[str]:
    if provider is None:
        return None
    return provider.value if hasattr(provider, "value") else str(provider)


def resolve_ai_provider(
    provider: Union[str, ModelProvider],
    db: Session,
    organization_id: UUID,
    *,
    credential_id: Optional[UUID] = None,
) -> Optional[AIProvider]:
    """Resolve a single AIProvider row for ``(provider, organization_id)``.

    Selection precedence:
        1. ``credential_id`` if provided (and the row matches the org +
           provider).
        2. The row marked ``is_default``.
        3. Most recently updated active row.
    """
    provider_value = _to_str(provider)
    if provider_value is None:
        return None

    base = db.query(AIProvider).filter(
        AIProvider.organization_id == organization_id,
        func.lower(AIProvider.provider) == provider_value.lower(),
    )

    if credential_id is not None:
        row = base.filter(AIProvider.id == credential_id).first()
        if row:
            return row
        # Fall through to default if the explicit id is stale (deleted / wrong org)

    default_row = base.filter(AIProvider.is_default.is_(True)).first()
    if default_row:
        return default_row

    return (
        base.filter(AIProvider.is_active.is_(True))
        .order_by(desc(AIProvider.updated_at), desc(AIProvider.created_at))
        .first()
    )


def resolve_voice_integration(
    platform: Union[str, ModelProvider],
    db: Session,
    organization_id: UUID,
    *,
    credential_id: Optional[UUID] = None,
    require_active: bool = True,
) -> Optional[Integration]:
    """Resolve a single Integration (voice platform) row.

    See :func:`resolve_ai_provider` for selection precedence.
    """
    platform_value = _to_str(platform)
    if platform_value is None:
        return None

    base = db.query(Integration).filter(
        Integration.organization_id == organization_id,
        func.lower(Integration.platform) == platform_value.lower(),
    )
    if require_active:
        base = base.filter(Integration.is_active.is_(True))

    if credential_id is not None:
        row = base.filter(Integration.id == credential_id).first()
        if row:
            return row

    default_row = base.filter(Integration.is_default.is_(True)).first()
    if default_row:
        return default_row

    return base.order_by(
        desc(Integration.updated_at), desc(Integration.created_at)
    ).first()


def resolve_telephony_integration(
    provider: str,
    db: Session,
    organization_id: UUID,
    *,
    credential_id: Optional[UUID] = None,
    require_active: bool = True,
) -> Optional[TelephonyIntegration]:
    """Resolve a single TelephonyIntegration row for ``(provider, org)``.

    See :func:`resolve_ai_provider` for selection precedence.
    """
    if not provider:
        return None

    base = db.query(TelephonyIntegration).filter(
        TelephonyIntegration.organization_id == organization_id,
        func.lower(TelephonyIntegration.provider) == provider.lower(),
    )
    if require_active:
        base = base.filter(TelephonyIntegration.is_active.is_(True))

    if credential_id is not None:
        row = base.filter(TelephonyIntegration.id == credential_id).first()
        if row:
            return row

    default_row = base.filter(TelephonyIntegration.is_default.is_(True)).first()
    if default_row:
        return default_row

    return base.order_by(
        desc(TelephonyIntegration.updated_at), desc(TelephonyIntegration.created_at)
    ).first()


def clear_other_defaults(
    model: Type[T],
    db: Session,
    organization_id: UUID,
    *,
    keep_id: UUID,
    provider_field: str,
    provider_value: str,
) -> None:
    """Clear ``is_default`` on every row in ``model`` for ``(org, provider)``
    except ``keep_id``. Caller is responsible for committing.
    """
    column = getattr(model, provider_field)
    db.query(model).filter(
        model.organization_id == organization_id,
        func.lower(column) == provider_value.lower(),
        model.id != keep_id,
        model.is_default.is_(True),
    ).update({model.is_default: False}, synchronize_session=False)
