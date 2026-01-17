"""Security utilities for API key validation."""

from typing import Optional
from sqlalchemy.orm import Session
from app.models.database import APIKey
from app.core.exceptions import InvalidAPIKeyError
from app.database import get_db


def verify_api_key(api_key: str, db: Session) -> bool:
    """
    Verify API key against database.
    Updates last_used timestamp when key is used.

    Args:
        api_key: The API key to verify
        db: Database session

    Returns:
        True if valid, False otherwise

    Raises:
        InvalidAPIKeyError: If API key is invalid
    """
    if not api_key:
        raise InvalidAPIKeyError("API key is required")

    db_key = db.query(APIKey).filter(APIKey.key == api_key, APIKey.is_active == True).first()

    if not db_key:
        raise InvalidAPIKeyError("Invalid API key")

    # Update last_used timestamp
    from datetime import datetime, timezone
    db_key.last_used = datetime.now(timezone.utc)
    db.commit()

    return True


def get_api_key_organization_id(api_key: str, db: Session):
    """
    Get organization ID from API key.

    Args:
        api_key: The API key
        db: Database session

    Returns:
        Organization ID (UUID) or None if not found
    """
    db_key = db.query(APIKey).filter(APIKey.key == api_key, APIKey.is_active == True).first()
    if db_key:
        return db_key.organization_id
    return None


def get_api_key_dependency(api_key: Optional[str] = None) -> str:
    """
    Dependency for FastAPI to extract and validate API key.

    Args:
        api_key: API key from header (injected by FastAPI)

    Returns:
        The validated API key

    Raises:
        InvalidAPIKeyError: If API key is invalid
    """
    from fastapi import Header, HTTPException
    from app.dependencies import get_db

    # This will be used as a dependency in routes
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

