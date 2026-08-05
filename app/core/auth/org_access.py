"""Organization access guards shared across auth providers."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.auth.providers import AuthError
from app.models.database import Organization


def ensure_organization_active(db: Session, organization_id: UUID) -> Organization:
    """Raise AuthError when the organization is missing or disabled."""
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if org is None:
        raise AuthError("Organization not found")
    if not org.is_active:
        raise AuthError("Organization disabled", status_code=403)
    return org
