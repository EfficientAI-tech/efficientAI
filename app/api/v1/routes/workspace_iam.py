"""Workspace IAM: membership and role management."""

from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import Principal, get_principal
from app.core.auth.capabilities import (
    WORKSPACE_MEMBERS_MANAGE,
    WORKSPACE_MEMBERS_VIEW,
    capability_denied_message,
    capabilities_for_registry,
    normalize_capabilities,
)
from app.core.auth.rbac import require_admin
from app.database import get_db
from app.dependencies import get_organization_id
from app.models.database import OrganizationMember, User, Workspace, WorkspaceMember, WorkspaceRole
from app.models.schemas import (
    CapabilityDomainResponse,
    WorkspaceMemberCreate,
    WorkspaceMemberResponse,
    WorkspaceMemberUpdate,
    WorkspaceRoleCreate,
    WorkspaceRoleResponse,
    WorkspaceRoleUpdate,
)
from app.services.workspace_rbac import (
    add_workspace_member,
    count_workspace_admins,
    is_workspace_admin_role,
    resolve_workspace_capabilities,
    seed_system_workspace_roles,
)


router = APIRouter(tags=["Workspace IAM"])


def _require_workspace_in_org(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
) -> Workspace:
    workspace = (
        db.query(Workspace)
        .filter(
            Workspace.id == workspace_id,
            Workspace.organization_id == organization_id,
        )
        .first()
    )
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    return workspace


def _require_workspace_capability(
    db: Session,
    *,
    principal: Principal,
    organization_id: UUID,
    workspace_id: UUID,
    capability: str,
) -> None:
    _require_workspace_in_org(
        db,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    caps, _, role = resolve_workspace_capabilities(
        db,
        principal=principal,
        workspace_id=workspace_id,
        organization_id=organization_id,
    )
    if capability not in caps:
        raise HTTPException(
            status_code=403,
            detail=capability_denied_message(
                capability,
                role_name=role.name if role else None,
            ),
        )


def _member_response(db: Session, member: WorkspaceMember) -> WorkspaceMemberResponse:
    user = db.query(User).filter(User.id == member.user_id).first()
    role = db.query(WorkspaceRole).filter(WorkspaceRole.id == member.role_id).first()
    return WorkspaceMemberResponse(
        id=member.id,
        workspace_id=member.workspace_id,
        user_id=member.user_id,
        role_id=member.role_id,
        role_name=role.name if role else "Unknown",
        user_email=user.email if user else "",
        user_name=user.name if user else None,
        added_by_user_id=member.added_by_user_id,
        created_at=member.created_at,
    )


@router.get("/capabilities", response_model=List[CapabilityDomainResponse])
def list_capabilities(
    organization_id: UUID = Depends(get_organization_id),
):
    """Return the capability registry for the role-builder UI."""
    del organization_id  # auth gate only; registry is static
    return capabilities_for_registry()


@router.get("/workspace-roles", response_model=List[WorkspaceRoleResponse])
def list_workspace_roles(
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    roles = (
        db.query(WorkspaceRole)
        .filter(WorkspaceRole.organization_id == organization_id)
        .order_by(WorkspaceRole.is_system.desc(), WorkspaceRole.name.asc())
        .all()
    )
    return roles


@router.post(
    "/workspace-roles",
    response_model=WorkspaceRoleResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def create_workspace_role(
    payload: WorkspaceRoleCreate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    caps = sorted(normalize_capabilities(payload.capabilities))
    if not caps:
        raise HTTPException(status_code=400, detail="At least one valid capability is required.")

    existing = (
        db.query(WorkspaceRole)
        .filter(
            WorkspaceRole.organization_id == organization_id,
            WorkspaceRole.name == payload.name.strip(),
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="A role with this name already exists.")

    role = WorkspaceRole(
        organization_id=organization_id,
        name=payload.name.strip(),
        description=payload.description,
        capabilities=caps,
        is_system=False,
    )
    db.add(role)
    db.commit()
    db.refresh(role)
    return role


@router.patch(
    "/workspace-roles/{role_id}",
    response_model=WorkspaceRoleResponse,
    dependencies=[Depends(require_admin)],
)
def update_workspace_role(
    role_id: UUID,
    payload: WorkspaceRoleUpdate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    role = (
        db.query(WorkspaceRole)
        .filter(
            WorkspaceRole.id == role_id,
            WorkspaceRole.organization_id == organization_id,
        )
        .first()
    )
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found.")
    if role.is_system:
        raise HTTPException(status_code=400, detail="System roles cannot be modified.")

    if payload.name is not None:
        role.name = payload.name.strip()
    if payload.description is not None:
        role.description = payload.description
    if payload.capabilities is not None:
        caps = sorted(normalize_capabilities(payload.capabilities))
        if not caps:
            raise HTTPException(status_code=400, detail="At least one valid capability is required.")
        role.capabilities = caps

    db.commit()
    db.refresh(role)
    return role


@router.delete(
    "/workspace-roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin)],
)
def delete_workspace_role(
    role_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    role = (
        db.query(WorkspaceRole)
        .filter(
            WorkspaceRole.id == role_id,
            WorkspaceRole.organization_id == organization_id,
        )
        .first()
    )
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found.")
    if role.is_system:
        raise HTTPException(status_code=400, detail="System roles cannot be deleted.")

    assigned = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.role_id == role_id)
        .count()
    )
    if assigned:
        raise HTTPException(
            status_code=409,
            detail="Role is assigned to workspace members and cannot be deleted.",
        )

    db.delete(role)
    db.commit()
    return None


@router.get("/workspaces/{workspace_id}/members", response_model=List[WorkspaceMemberResponse])
def list_workspace_members(
    workspace_id: UUID,
    principal: Principal = Depends(get_principal),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    _require_workspace_capability(
        db,
        principal=principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        capability=WORKSPACE_MEMBERS_VIEW,
    )
    members = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.workspace_id == workspace_id)
        .order_by(WorkspaceMember.created_at.asc())
        .all()
    )
    return [_member_response(db, member) for member in members]


@router.post(
    "/workspaces/{workspace_id}/members",
    response_model=WorkspaceMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_workspace_member_route(
    workspace_id: UUID,
    payload: WorkspaceMemberCreate,
    principal: Principal = Depends(get_principal),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    _require_workspace_capability(
        db,
        principal=principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        capability=WORKSPACE_MEMBERS_MANAGE,
    )

    org_member = (
        db.query(OrganizationMember)
        .filter(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == payload.user_id,
        )
        .first()
    )
    if org_member is None:
        raise HTTPException(status_code=400, detail="User is not a member of this organization.")

    role = (
        db.query(WorkspaceRole)
        .filter(
            WorkspaceRole.id == payload.role_id,
            WorkspaceRole.organization_id == organization_id,
        )
        .first()
    )
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found.")

    member = add_workspace_member(
        db,
        workspace_id=workspace_id,
        user_id=payload.user_id,
        role_id=payload.role_id,
        added_by_user_id=principal.user_id,
    )
    db.commit()
    db.refresh(member)
    return _member_response(db, member)


@router.patch(
    "/workspaces/{workspace_id}/members/{user_id}",
    response_model=WorkspaceMemberResponse,
)
def update_workspace_member_route(
    workspace_id: UUID,
    user_id: UUID,
    payload: WorkspaceMemberUpdate,
    principal: Principal = Depends(get_principal),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    _require_workspace_capability(
        db,
        principal=principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        capability=WORKSPACE_MEMBERS_MANAGE,
    )

    member = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
        .first()
    )
    if member is None:
        raise HTTPException(status_code=404, detail="Workspace member not found.")

    new_role = (
        db.query(WorkspaceRole)
        .filter(
            WorkspaceRole.id == payload.role_id,
            WorkspaceRole.organization_id == organization_id,
        )
        .first()
    )
    if new_role is None:
        raise HTTPException(status_code=404, detail="Role not found.")

    old_role = db.query(WorkspaceRole).filter(WorkspaceRole.id == member.role_id).first()
    is_self = principal.user_id == user_id
    if (
        is_self
        and is_workspace_admin_role(old_role)
        and not is_workspace_admin_role(new_role)
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "You cannot demote your own Workspace Admin role. "
                "Ask another admin to change your role."
            ),
        )
    if is_workspace_admin_role(old_role) and not is_workspace_admin_role(new_role):
        if count_workspace_admins(db, workspace_id=workspace_id) <= 1:
            raise HTTPException(
                status_code=409,
                detail="Cannot demote the last Workspace Admin of this workspace.",
            )

    member.role_id = payload.role_id
    db.commit()
    db.refresh(member)
    return _member_response(db, member)


@router.delete(
    "/workspaces/{workspace_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_workspace_member_route(
    workspace_id: UUID,
    user_id: UUID,
    principal: Principal = Depends(get_principal),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    _require_workspace_in_org(
        db,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )

    is_self = principal.user_id == user_id
    if not is_self:
        _require_workspace_capability(
            db,
            principal=principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            capability=WORKSPACE_MEMBERS_MANAGE,
        )

    member = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
        .first()
    )
    if member is None:
        raise HTTPException(status_code=404, detail="Workspace member not found.")

    role = db.query(WorkspaceRole).filter(WorkspaceRole.id == member.role_id).first()
    if is_workspace_admin_role(role) and count_workspace_admins(db, workspace_id=workspace_id) <= 1:
        raise HTTPException(
            status_code=409,
            detail="Cannot remove the last Workspace Admin of this workspace.",
        )

    db.delete(member)
    db.commit()
    return None
