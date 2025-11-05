"""Common dependencies for FastAPI routes."""

from fastapi import Header, HTTPException, Depends
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from uuid import UUID
from app.database import get_db
from app.core.security import verify_api_key, get_api_key_organization_id
from app.core.exceptions import InvalidAPIKeyError


def get_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> str:
    """
    Extract and validate API key from request header.

    Args:
        x_api_key: API key from X-API-Key header

    Returns:
        Validated API key

    Raises:
        HTTPException: If API key is missing or invalid
    """
    if not x_api_key:
        raise HTTPException(status_code=401, detail="API key is required")

    db = next(get_db())
    try:
        verify_api_key(x_api_key, db)
        return x_api_key
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

