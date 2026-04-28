"""
Role-based access control (RBAC) helpers shared across all API routes.

This module is the single source of truth for "what can role X do?" inside an
organization. It exposes:

    - `RoleLevel`               numeric ordering of `RoleEnum` (reader < writer < admin)
    - `get_org_role`            resolve the caller's role in their current org
    - `require_role(min_role)`  FastAPI dependency factory enforcing minimum role
    - `require_admin`           sugar for `require_role(RoleEnum.ADMIN)`
    - `require_writer`          sugar for `require_role(RoleEnum.WRITER)`
    - `require_reader`          sugar for `require_role(RoleEnum.READER)`

Why a hierarchy: roles in this app are strictly cumulative. Admin can do
everything a Writer can; Writer can do everything a Reader can. So most route
guards want "this caller is at least X", not "this caller is exactly X".
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.dependency import get_principal
from app.database import get_db
from app.models.database import OrganizationMember, RoleEnum


# Numeric ordering so we can express "at least writer" as a single comparison.
# Higher number = more privilege.
RoleLevel = {
    RoleEnum.READER: 1,
    RoleEnum.WRITER: 2,
    RoleEnum.ADMIN: 3,
}


def _coerce_role(raw) -> Optional[RoleEnum]:
    """Membership.role can come back as an enum or a plain string depending on
    the backing DB (SQLite drops enum metadata on round-trip). Normalize."""
    if raw is None:
        return None
    if isinstance(raw, RoleEnum):
        return raw
    try:
        return RoleEnum(str(raw))
    except ValueError:
        return None


def get_org_role(
    principal: Principal,
    db: Session,
) -> Optional[RoleEnum]:
    """
    Look up the caller's role in their current organization.

    Returns None if the caller is not a member of the org pinned to their
    credential. That should normally not happen (auth providers verify
    membership at issue time) but we treat it defensively as "no role".
    """
    if principal.user_id is None:
        return None

    member = (
        db.query(OrganizationMember)
        .filter(
            OrganizationMember.organization_id == principal.organization_id,
            OrganizationMember.user_id == principal.user_id,
        )
        .first()
    )
    if not member:
        return None
    return _coerce_role(member.role)


def require_role(min_role: RoleEnum):
    """
    Build a FastAPI dependency that ensures the caller has at least `min_role`.

    Usage:

        @router.post("/agents", dependencies=[Depends(require_role(RoleEnum.WRITER))])

    Or, when the route also wants the principal:

        def create_agent(
            principal: Principal = Depends(get_principal),
            _: None = Depends(require_role(RoleEnum.WRITER)),
        ): ...
    """
    needed = RoleLevel[min_role]

    def _dep(
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Principal:
        role = get_org_role(principal, db)
        if role is None or RoleLevel[role] < needed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"This action requires {min_role.value} role or higher. "
                    f"Your current role is {role.value if role else 'none'}."
                ),
            )
        return principal

    return _dep


# Convenience aliases so call sites read naturally.
require_admin = require_role(RoleEnum.ADMIN)
require_writer = require_role(RoleEnum.WRITER)
require_reader = require_role(RoleEnum.READER)


def get_current_org_role(
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> Optional[RoleEnum]:
    """FastAPI dependency that returns the caller's role without enforcing it.

    Useful for routes that need to branch on role (e.g. tailoring a response)
    rather than reject outright.
    """
    return get_org_role(principal, db)
