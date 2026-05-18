"""Workspace management routes.

Workspaces are the in-org isolation boundary picked up by the
``X-Workspace-Id`` header (see ``app.dependencies.get_workspace_id``).
Members can list, create, rename and delete workspaces within their
own organization; the Default workspace can never be deleted because
the rest of the system uses it as the fallback when a request arrives
without an explicit workspace header.
"""

from __future__ import annotations

import re
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_organization_id
from app.models.database import Workspace
from app.models.schemas import (
    WorkspaceCreate,
    WorkspaceResponse,
    WorkspaceUpdate,
)


router = APIRouter(prefix="/workspaces", tags=["Workspaces"])


# Slugs use underscores so they round-trip cleanly through the UI and URL
# path (no percent-encoded hyphens, no collisions with our default
# ``"default"`` slug).
_SLUG_PATTERN = re.compile(r"[^a-z0-9_]+")


def _slugify(value: str) -> str:
    """Best-effort slug derivation from a display name.

    Lower-cases, replaces runs of non-alphanumerics with underscores,
    and trims leading/trailing underscores. Empty inputs collapse to
    ``"workspace"`` so we never persist an empty slug.
    """
    cleaned = _SLUG_PATTERN.sub("_", value.strip().lower()).strip("_")
    return cleaned or "workspace"


@router.get("", response_model=List[WorkspaceResponse])
def list_workspaces(
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """List every workspace in the caller's organization."""
    workspaces = (
        db.query(Workspace)
        .filter(Workspace.organization_id == organization_id)
        # Default first, then alphabetical so the UI list reads naturally.
        .order_by(Workspace.is_default.desc(), Workspace.name.asc())
        .all()
    )
    return workspaces


@router.post(
    "",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_workspace(
    payload: WorkspaceCreate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Create a new (non-default) workspace in the caller's org."""
    slug = (payload.slug or _slugify(payload.name)).strip().lower()
    if not slug:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Workspace slug cannot be empty.",
        )

    # Pre-check the slug so we can return a clean 409 even on backends
    # whose IntegrityError messages don't include the constraint name
    # (e.g. SQLite in tests). We still rely on the unique index for
    # the race-condition safety net below.
    existing = (
        db.query(Workspace)
        .filter(
            Workspace.organization_id == organization_id,
            Workspace.slug == slug,
        )
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A workspace with slug '{slug}' already exists in "
                "this organization."
            ),
        )

    workspace = Workspace(
        organization_id=organization_id,
        name=payload.name.strip(),
        slug=slug,
        is_default=False,
    )
    db.add(workspace)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        message = str(exc.orig).lower()
        if "uq_workspaces_org_slug" in message or "unique" in message:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"A workspace with slug '{slug}' already exists in "
                    "this organization."
                ),
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not create workspace.",
        )
    db.refresh(workspace)
    return workspace


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
def update_workspace(
    workspace_id: UUID,
    payload: WorkspaceUpdate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Rename a workspace (slug stays put to keep deep-links stable)."""
    workspace = (
        db.query(Workspace)
        .filter(
            Workspace.id == workspace_id,
            Workspace.organization_id == organization_id,
        )
        .first()
    )
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found.",
        )

    workspace.name = payload.name.strip()
    db.commit()
    db.refresh(workspace)
    return workspace


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace(
    workspace_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Delete a non-default workspace.

    The Default workspace is the safety net for headerless requests and
    legacy rows, so it can never be deleted. Workspaces that still own
    resources will be rejected by the ``ON DELETE RESTRICT`` FKs
    declared in migrations 033/034 and surface here as a 409.
    """
    workspace = (
        db.query(Workspace)
        .filter(
            Workspace.id == workspace_id,
            Workspace.organization_id == organization_id,
        )
        .first()
    )
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found.",
        )
    if workspace.is_default:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The default workspace cannot be deleted.",
        )

    db.delete(workspace)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Workspace still contains resources. Move or delete "
                "them before removing the workspace."
            ),
        )
    return None
