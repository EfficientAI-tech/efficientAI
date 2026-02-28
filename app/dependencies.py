"""Common dependencies for FastAPI routes."""

from fastapi import Header, HTTPException, Depends
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from uuid import UUID
from app.database import get_db
from app.core.security import verify_api_key, get_api_key_organization_id
from app.core.exceptions import InvalidAPIKeyError
from app.core.license import is_feature_enabled


def get_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    x_efficientai_api_key: Optional[str] = Header(
        None, alias="X-EFFICIENTAI-API-KEY"
    ),
) -> str:
    """
    Extract and validate API key from request headers.

    Args:
        x_api_key: API key from X-API-Key header (legacy/SDK usage)
        x_efficientai_api_key: API key from X-EFFICIENTAI-API-KEY header (webhooks)

    Returns:
        Validated API key

    Raises:
        HTTPException: If API key is missing or invalid
    """
    api_key = x_api_key or x_efficientai_api_key

    if not api_key:
        raise HTTPException(status_code=401, detail="API key is required")

    db = next(get_db())
    try:
        verify_api_key(api_key, db)
        return api_key
    except InvalidAPIKeyError as e:
        raise HTTPException(status_code=401, detail=str(e))
    finally:
        db.close()


def get_organization_id(
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
) -> UUID:
    """
    Get organization ID from validated API key.

    Args:
        api_key: Validated API key from get_api_key dependency
        db: Database session

    Returns:
        Organization ID

    Raises:
        HTTPException: If organization not found
    """
    organization_id = get_api_key_organization_id(api_key, db)
    if not organization_id:
        raise HTTPException(status_code=500, detail="Organization not found for API key")
    return organization_id


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
        x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
        x_efficientai_api_key: Optional[str] = Header(None, alias="X-EFFICIENTAI-API-KEY"),
        db: Session = Depends(get_db),
    ):
        organization_id = None
        api_key = x_api_key or x_efficientai_api_key
        if api_key:
            try:
                organization_id = get_api_key_organization_id(api_key, db)
            except Exception:
                pass

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

