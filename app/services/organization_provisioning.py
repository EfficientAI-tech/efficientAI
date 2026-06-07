"""Shared helpers for provisioning organization resources."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import Workspace


def provision_default_workspace(
    db: Session,
    *,
    organization_id: UUID,
    created_by_user_id: UUID | None = None,
) -> Workspace:
    """Create the canonical Default workspace for an organization (idempotent)."""
    existing = (
        db.query(Workspace)
        .filter(
            Workspace.organization_id == organization_id,
            Workspace.is_default.is_(True),
        )
        .first()
    )
    if existing is not None:
        return existing

    workspace = Workspace(
        organization_id=organization_id,
        name="Default",
        slug="default",
        is_default=True,
        created_by_user_id=created_by_user_id,
    )
    db.add(workspace)
    db.flush()
    return workspace
