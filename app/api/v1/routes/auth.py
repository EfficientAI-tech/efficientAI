"""Authentication routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import secrets
from app.database import get_db
from app.models.database import APIKey, Organization
from app.models.schemas import APIKeyCreate, APIKeyResponse
from app.dependencies import get_api_key

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/generate-key", response_model=APIKeyResponse)
def generate_api_key(key_data: APIKeyCreate, db: Session = Depends(get_db)):
    """
    Generate a new API key.
    Creates a new organization for the first API key, or uses existing organization
    if one already exists for this user (based on name or other criteria).

    Args:
        key_data: API key creation data
        db: Database session

    Returns:
        Created API key
    """
    # Generate secure random API key
    api_key = secrets.token_urlsafe(32)

    # Create or get organization
    # For now, create a new organization for each API key
    # You can modify this logic to reuse organizations based on business rules
    org_name = key_data.name or f"Organization-{secrets.token_urlsafe(8)}"
    organization = Organization(name=org_name)
    db.add(organization)
    db.flush()  # Flush to get the organization ID without committing

    # Create API key record with organization
    db_key = APIKey(key=api_key, name=key_data.name, organization_id=organization.id)
    db.add(db_key)
    db.commit()
    db.refresh(db_key)
    db.refresh(organization)

    return db_key


@router.post("/validate")
def validate_api_key(api_key: str = Depends(get_api_key)):
    """
    Validate API key (for testing).

    Args:
        api_key: Validated API key from dependency

    Returns:
        Validation confirmation
    """
    return {"valid": True, "message": "API key is valid"}

