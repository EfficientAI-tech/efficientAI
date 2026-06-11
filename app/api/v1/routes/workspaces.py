"""Workspace management routes with capability-based access control."""

from __future__ import annotations

import re
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import Principal, get_principal
from app.core.auth.capabilities import WORKSPACE_SETTINGS
from app.core.auth.rbac import get_org_role, require_admin, require_writer
from app.database import get_db
from app.dependencies import get_organization_id
from app.models.database import RoleEnum, Workspace, WorkspaceMember, WorkspaceRole
from app.models.schemas import (
    WorkspaceCreate,
    WorkspaceResponse,
    WorkspaceUpdate,
)
from app.services.workspace_rbac import (
    ensure_creator_workspace_admin,
    resolve_workspace_capabilities,
    seed_system_workspace_roles,
)


router = APIRouter(prefix="/workspaces", tags=["Workspaces"])

_SLUG_PATTERN = re.compile(r"[^a-z0-9_]+")


def _slugify(value: str) -> str:
    cleaned = _SLUG_PATTERN.sub("_", value.strip().lower()).strip("_")
    return cleaned or "workspace"


def _workspace_response(
    db: Session,
    *,
    workspace: Workspace,
    principal: Principal,
) -> WorkspaceResponse:
    caps, _membership, role = resolve_workspace_capabilities(
        db,
        principal=principal,
        workspace_id=workspace.id,
        organization_id=workspace.organization_id,
    )
    return WorkspaceResponse(
        id=workspace.id,
        organization_id=workspace.organization_id,
        name=workspace.name,
        slug=workspace.slug,
        is_default=workspace.is_default,
        created_at=workspace.created_at,
        updated_at=workspace.updated_at,
        role_id=role.id if role else None,
        role_name=role.name if role else ("Org Admin" if caps else None),
        capabilities=sorted(caps),
    )


@router.get("", response_model=List[WorkspaceResponse])
def list_workspaces(
    principal: Principal = Depends(get_principal),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """List workspaces the caller can access."""
    org_role = get_org_role(principal, db)
    query = db.query(Workspace).filter(Workspace.organization_id == organization_id)

    if org_role != RoleEnum.ADMIN and principal.user_id is not None:
        member_ws_ids = [
            row[0]
            for row in db.query(WorkspaceMember.workspace_id)
            .filter(WorkspaceMember.user_id == principal.user_id)
            .all()
        ]
        if not member_ws_ids:
            return []
        query = query.filter(Workspace.id.in_(member_ws_ids))

    workspaces = query.order_by(Workspace.is_default.desc(), Workspace.name.asc()).all()
    return [_workspace_response(db, workspace=ws, principal=principal) for ws in workspaces]


@router.post(
    "",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_writer)],
)
def create_workspace(
    payload: WorkspaceCreate,
    principal: Principal = Depends(get_principal),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Create a new (non-default) workspace; creator becomes Workspace Admin."""
    slug = (payload.slug or _slugify(payload.name)).strip().lower()
    if not slug:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Workspace slug cannot be empty.",
        )

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
            detail=f"A workspace with slug '{slug}' already exists in this organization.",
        )

    seed_system_workspace_roles(db, organization_id=organization_id)

    workspace = Workspace(
        organization_id=organization_id,
        name=payload.name.strip(),
        slug=slug,
        is_default=False,
        created_by_user_id=principal.user_id,
    )
    db.add(workspace)
    try:
        db.flush()
        ensure_creator_workspace_admin(
            db,
            workspace=workspace,
            user_id=principal.user_id,
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        message = str(exc.orig).lower()
        if "uq_workspaces_org_slug" in message or "unique" in message:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A workspace with slug '{slug}' already exists in this organization.",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not create workspace.",
        )
    db.refresh(workspace)
    return _workspace_response(db, workspace=workspace, principal=principal)


@router.patch(
    "/{workspace_id}",
    response_model=WorkspaceResponse,
)
def update_workspace(
    workspace_id: UUID,
    payload: WorkspaceUpdate,
    principal: Principal = Depends(get_principal),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Rename a workspace (slug stays put to keep deep-links stable)."""
    caps, _, _ = resolve_workspace_capabilities(
        db,
        principal=principal,
        workspace_id=workspace_id,
        organization_id=organization_id,
    )
    if WORKSPACE_SETTINGS not in caps:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"This action requires the '{WORKSPACE_SETTINGS}' capability in this workspace.",
        )

    workspace = (
        db.query(Workspace)
        .filter(
            Workspace.id == workspace_id,
            Workspace.organization_id == organization_id,
        )
        .first()
    )
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")

    workspace.name = payload.name.strip()
    db.commit()
    db.refresh(workspace)
    return _workspace_response(db, workspace=workspace, principal=principal)


@router.delete(
    "/{workspace_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin)],
)
def delete_workspace(
    workspace_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Delete a non-default workspace (org admin only)."""
    workspace = (
        db.query(Workspace)
        .filter(
            Workspace.id == workspace_id,
            Workspace.organization_id == organization_id,
        )
        .first()
    )
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
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
            detail="Workspace still contains resources. Move or delete them before removing the workspace.",
        )
    return None
