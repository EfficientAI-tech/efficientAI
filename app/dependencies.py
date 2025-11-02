"""Common dependencies for FastAPI routes."""

from fastapi import Header, HTTPException
from typing import Optional
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.security import verify_api_key
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


def get_db_session() -> Session:
    """
    Get database session.

    Yields:
        Database session
    """
    return next(get_db())

