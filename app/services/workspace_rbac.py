"""Workspace RBAC helpers: role seeding, membership, capability resolution."""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.auth.capabilities import (
    EDITOR_ROLE_CAPABILITIES,
    SYSTEM_ROLE_ADMIN,
    SYSTEM_ROLE_EDITOR,
    SYSTEM_ROLE_VIEWER,
    VIEWER_ROLE_CAPABILITIES,
    WORKSPACE_ADMIN_ROLE_CAPABILITIES,
    normalize_capabilities,
)
from app.core.auth.rbac import get_org_role
from app.core.auth.principal import Principal
from app.models.database import (
    OrganizationMember,
    RoleEnum,
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
)


SYSTEM_ROLE_DEFINITIONS: Tuple[Tuple[str, str, List[str]], ...] = (
    (SYSTEM_ROLE_VIEWER, "Read-only access to workspace resources.", VIEWER_ROLE_CAPABILITIES),
    (
        SYSTEM_ROLE_EDITOR,
        "View and modify workspace resources without admin settings.",
        EDITOR_ROLE_CAPABILITIES,
    ),
    (
        SYSTEM_ROLE_ADMIN,
        "Full access including workspace settings and member management.",
        WORKSPACE_ADMIN_ROLE_CAPABILITIES,
    ),
)


def seed_system_workspace_roles(
    db: Session,
    *,
    organization_id: UUID,
) -> Dict[str, WorkspaceRole]:
    """Ensure the three system roles exist for an organization (idempotent)."""
    by_name: Dict[str, WorkspaceRole] = {}
    for name, description, capabilities in SYSTEM_ROLE_DEFINITIONS:
        role = (
            db.query(WorkspaceRole)
            .filter(
                WorkspaceRole.organization_id == organization_id,
                WorkspaceRole.name == name,
            )
            .first()
        )
        if role is None:
            role = WorkspaceRole(
                organization_id=organization_id,
                name=name,
                description=description,
                capabilities=capabilities,
                is_system=True,
            )
            db.add(role)
            db.flush()
        by_name[name] = role
    return by_name


def org_role_to_system_workspace_role(org_role: Optional[RoleEnum | str]) -> str:
    """Map org membership role to a system workspace role name for backfill."""
    if isinstance(org_role, str):
        try:
            org_role = RoleEnum(org_role)
        except ValueError:
            org_role = RoleEnum.READER
    if org_role == RoleEnum.ADMIN:
        return SYSTEM_ROLE_ADMIN
    if org_role == RoleEnum.WRITER:
        return SYSTEM_ROLE_EDITOR
    return SYSTEM_ROLE_VIEWER


def add_workspace_member(
    db: Session,
    *,
    workspace_id: UUID,
    user_id: UUID,
    role_id: UUID,
    added_by_user_id: UUID | None = None,
) -> WorkspaceMember:
    """Add or update a workspace membership."""
    existing = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
        .first()
    )
    if existing is not None:
        existing.role_id = role_id
        if added_by_user_id is not None:
            existing.added_by_user_id = added_by_user_id
        db.flush()
        return existing

    member = WorkspaceMember(
        workspace_id=workspace_id,
        user_id=user_id,
        role_id=role_id,
        added_by_user_id=added_by_user_id,
    )
    db.add(member)
    db.flush()
    return member


def ensure_creator_workspace_admin(
    db: Session,
    *,
    workspace: Workspace,
    user_id: UUID | None,
) -> None:
    """Auto-add workspace creator as Workspace Admin."""
    if user_id is None:
        return
    roles = seed_system_workspace_roles(db, organization_id=workspace.organization_id)
    admin_role = roles[SYSTEM_ROLE_ADMIN]
    add_workspace_member(
        db,
        workspace_id=workspace.id,
        user_id=user_id,
        role_id=admin_role.id,
        added_by_user_id=user_id,
    )


def resolve_workspace_capabilities(
    db: Session,
    *,
    principal: Principal,
    workspace_id: UUID,
    organization_id: UUID,
) -> Tuple[Set[str], Optional[WorkspaceMember], Optional[WorkspaceRole]]:
    """
    Resolve the caller's capability set for a workspace.

    Returns (capabilities, membership_row, role_row). Org admins and unbound
    API keys receive all capabilities with no membership row.
    """
    from app.core.auth.capabilities import ALL_CAPABILITIES

    org_role = get_org_role(principal, db)
    if org_role == RoleEnum.ADMIN:
        return set(ALL_CAPABILITIES), None, None

    if principal.user_id is None:
        return set(ALL_CAPABILITIES), None, None

    membership = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == principal.user_id,
        )
        .first()
    )
    if membership is None:
        return set(), None, None

    role = db.query(WorkspaceRole).filter(WorkspaceRole.id == membership.role_id).first()
    if role is None:
        return set(), membership, None

    return normalize_capabilities(role.capabilities), membership, role


def is_workspace_admin_role(role: WorkspaceRole | None) -> bool:
    if role is None:
        return False
    caps = normalize_capabilities(role.capabilities)
    from app.core.auth.capabilities import WORKSPACE_SETTINGS, WORKSPACE_MEMBERS_MANAGE

    return WORKSPACE_SETTINGS in caps and WORKSPACE_MEMBERS_MANAGE in caps


def count_workspace_admins(db: Session, *, workspace_id: UUID) -> int:
    """Count members whose role includes workspace admin capabilities."""
    members = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.workspace_id == workspace_id)
        .all()
    )
    count = 0
    for member in members:
        role = db.query(WorkspaceRole).filter(WorkspaceRole.id == member.role_id).first()
        if is_workspace_admin_role(role):
            count += 1
    return count


def backfill_org_workspace_memberships(db: Session, *, organization_id: UUID) -> None:
    """Add every org member to every org workspace (idempotent)."""
    roles = seed_system_workspace_roles(db, organization_id=organization_id)
    workspaces = (
        db.query(Workspace)
        .filter(Workspace.organization_id == organization_id)
        .all()
    )
    members = (
        db.query(OrganizationMember)
        .filter(OrganizationMember.organization_id == organization_id)
        .all()
    )
    for org_member in members:
        role_name = org_role_to_system_workspace_role(org_member.role)
        ws_role = roles[role_name]
        for workspace in workspaces:
            existing = (
                db.query(WorkspaceMember)
                .filter(
                    WorkspaceMember.workspace_id == workspace.id,
                    WorkspaceMember.user_id == org_member.user_id,
                )
                .first()
            )
            if existing is None:
                add_workspace_member(
                    db,
                    workspace_id=workspace.id,
                    user_id=org_member.user_id,
                    role_id=ws_role.id,
                )
