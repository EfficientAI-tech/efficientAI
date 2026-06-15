"""Common dependencies for FastAPI routes.

The codebase historically exposed `get_api_key` and `get_organization_id` as
per-route dependencies. Both now sit on top of the pluggable auth system in
`app.core.auth`, so any route that used them transparently accepts Bearer
tokens from local password or SSO logins in addition to API keys.

New code should prefer `get_principal` directly: it returns a `Principal`
which carries user_id, organization_id, and auth_method in one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Set
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.auth import Principal, get_principal  # noqa: F401 - re-exported
from app.core.auth.rbac import get_org_role
from app.core.license import is_feature_enabled
from app.database import get_db
from app.models.database import RoleEnum, Workspace, WorkspaceMember
from app.core.auth.capabilities import capability_denied_message
from app.services.workspace_rbac import resolve_workspace_capabilities


def get_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    x_efficientai_api_key: Optional[str] = Header(
        None, alias="X-EFFICIENTAI-API-KEY"
    ),
    principal: Principal = Depends(get_principal),
) -> str:
    """
    Backward-compatible API key dependency.

    Authentication is fully delegated to `get_principal`, so this dep no longer
    rejects Bearer tokens. It returns the raw API key string when the caller
    used one (most routes don't read the value - they only depend on this to
    gate auth), or an empty string when the caller authenticated via Bearer.

    Prefer `get_principal` in new code.
    """
    return x_api_key or x_efficientai_api_key or ""


def get_organization_id(
    principal: Principal = Depends(get_principal),
) -> UUID:
    """
    Return the organization id of the authenticated caller.

    Works uniformly for API key and Bearer (local password / SSO) authentication
    because both paths produce a `Principal`.
    """
    return principal.organization_id


@dataclass(frozen=True)
class WorkspaceContext:
    """Resolved active workspace plus the caller's capabilities within it."""

    workspace_id: UUID
    organization_id: UUID
    capabilities: frozenset[str]
    role_id: UUID | None = None
    role_name: str | None = None
    is_org_admin: bool = False


def _resolve_workspace_row(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID | None,
    principal: Principal,
) -> Workspace:
    org_role = get_org_role(principal, db)
    is_org_admin = org_role == RoleEnum.ADMIN

    if workspace_id is not None:
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
                status_code=404,
                detail="Workspace not found in this organization.",
            )
        if not is_org_admin and principal.user_id is not None:
            member = (
                db.query(WorkspaceMember)
                .filter(
                    WorkspaceMember.workspace_id == workspace.id,
                    WorkspaceMember.user_id == principal.user_id,
                )
                .first()
            )
            if member is None:
                raise HTTPException(
                    status_code=403,
                    detail="You don't have access to this workspace.",
                )
        return workspace

    if is_org_admin or principal.user_id is None:
        default_ws = (
            db.query(Workspace)
            .filter(
                Workspace.organization_id == organization_id,
                Workspace.is_default.is_(True),
            )
            .first()
        )
        if default_ws is None:
            raise HTTPException(
                status_code=500,
                detail=(
                    "No default workspace exists for this organization. "
                    "Please contact support; migration 033 may not have run."
                ),
            )
        return default_ws

    membership_rows = (
        db.query(WorkspaceMember, Workspace)
        .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
        .filter(
            Workspace.organization_id == organization_id,
            WorkspaceMember.user_id == principal.user_id,
        )
        .order_by(Workspace.is_default.desc(), Workspace.name.asc())
        .all()
    )
    if not membership_rows:
        raise HTTPException(
            status_code=403,
            detail="You don't have access to any workspace in this organization.",
        )
    return membership_rows[0][1]


def get_workspace_context(
    request: Request,
    x_workspace_id: Optional[str] = Header(None, alias="X-Workspace-Id"),
    principal: Principal = Depends(get_principal),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> WorkspaceContext:
    """Resolve workspace + capability set once per request (cached on request.state)."""
    cached = getattr(request.state, "workspace_context", None)
    if cached is not None:
        return cached

    parsed_ws_id: UUID | None = None
    if x_workspace_id:
        try:
            parsed_ws_id = UUID(x_workspace_id)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=400,
                detail="X-Workspace-Id must be a valid UUID.",
            )

    workspace = _resolve_workspace_row(
        db,
        organization_id=organization_id,
        workspace_id=parsed_ws_id,
        principal=principal,
    )
    capabilities, membership, role = resolve_workspace_capabilities(
        db,
        principal=principal,
        workspace_id=workspace.id,
        organization_id=organization_id,
    )
    org_role = get_org_role(principal, db)
    ctx = WorkspaceContext(
        workspace_id=workspace.id,
        organization_id=organization_id,
        capabilities=frozenset(capabilities),
        role_id=role.id if role else (membership.role_id if membership else None),
        role_name=role.name if role else None,
        is_org_admin=org_role == RoleEnum.ADMIN,
    )
    request.state.workspace_context = ctx
    return ctx


def get_workspace_id(
    ctx: WorkspaceContext = Depends(get_workspace_context),
) -> UUID:
    """Return the active workspace UUID for the authenticated caller."""
    return ctx.workspace_id


def get_workspace_capabilities(
    ctx: WorkspaceContext = Depends(get_workspace_context),
) -> Set[str]:
    """Return the caller's capability set for the active workspace."""
    return set(ctx.capabilities)


def require_capability(capability: str):
    """
    Build a FastAPI dependency that ensures the caller has a workspace capability.

    Requires ``get_workspace_context`` to have run (directly or via
    ``get_workspace_id``) so capabilities are resolved for the active workspace.
    Org admins and unbound API keys receive all capabilities implicitly.
    """

    def _dep(ctx: WorkspaceContext = Depends(get_workspace_context)) -> WorkspaceContext:
        if capability not in ctx.capabilities:
            raise HTTPException(
                status_code=403,
                detail=capability_denied_message(
                    capability,
                    role_name=ctx.role_name,
                    workspace_label="the active workspace",
                ),
            )
        return ctx

    return _dep


def get_db_session() -> Session:
    """
    Get database session.

    Yields:
        Database session
    """
    return next(get_db())


def require_enterprise_feature(feature: str):
    """
    FastAPI dependency factory that gates a route behind an enterprise feature.

    When the license contains an org_id, the requesting organization must match.
    When org_id is absent from the license, the feature is enabled deployment-wide.

    Usage:
        router = APIRouter(
            dependencies=[Depends(require_enterprise_feature("voice_playground"))]
        )
    """

    def _check(
        organization_id: UUID = Depends(get_organization_id),
    ):
        if not is_feature_enabled(feature, organization_id):
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "enterprise_feature_required",
                    "feature": feature,
                    "message": (
                        f"'{feature}' is an EfficientAI Enterprise feature. "
                        "Please set EFFICIENTAI_LICENSE in your environment to unlock it. "
                        "Contact sales@efficientai.com to get an enterprise license key."
                    ),
                },
            )

    return _check
