"""Common dependencies for FastAPI routes.

The codebase historically exposed `get_api_key` and `get_organization_id` as
per-route dependencies. Both now sit on top of the pluggable auth system in
`app.core.auth`, so any route that used them transparently accepts Bearer
tokens from local password or SSO logins in addition to API keys.

New code should prefer `get_principal` directly: it returns a `Principal`
which carries user_id, organization_id, and auth_method in one place.
"""

from typing import Optional
from uuid import UUID

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import Principal, get_principal  # noqa: F401 - re-exported
from app.core.license import is_feature_enabled
from app.database import get_db
from app.models.database import Workspace


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


def get_workspace_id(
    x_workspace_id: Optional[str] = Header(None, alias="X-Workspace-Id"),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> UUID:
    """Return the active workspace UUID for the authenticated caller.

    Resolution order:
      1. ``X-Workspace-Id`` header. The referenced workspace must belong
         to the caller's organization, otherwise we 404 (don't leak the
         existence of another org's workspace).
      2. The organization's Default workspace (``is_default = True``).
         This is the back-compat path for existing API-key consumers
         that don't know about workspaces yet - migration 033 seeds a
         Default for every org so this always resolves.

    A 500 is raised if step 2 fails because the migration didn't run;
    callers should never see that in healthy deployments.
    """

    if x_workspace_id:
        try:
            ws_id = UUID(x_workspace_id)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=400,
                detail="X-Workspace-Id must be a valid UUID.",
            )
        ws = (
            db.query(Workspace)
            .filter(
                Workspace.id == ws_id,
                Workspace.organization_id == organization_id,
            )
            .first()
        )
        if ws is None:
            raise HTTPException(
                status_code=404, detail="Workspace not found in this organization."
            )
        return ws.id

    default_ws = (
        db.query(Workspace)
        .filter(
            Workspace.organization_id == organization_id,
            Workspace.is_default.is_(True),
        )
        .first()
    )
    if default_ws is None:
        # Should never happen post-migration. Raising 500 is preferable
        # to silently writing rows with a NULL workspace_id and tripping
        # the NOT NULL constraint downstream.
        raise HTTPException(
            status_code=500,
            detail=(
                "No default workspace exists for this organization. "
                "Please contact support; migration 033 may not have run."
            ),
        )
    return default_ws.id


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
