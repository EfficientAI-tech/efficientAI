"""
Settings API Routes
Manage API keys for authenticated users
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID
from datetime import datetime, timezone
import secrets
from pydantic import BaseModel

from app.dependencies import get_db, get_api_key
from app.models.database import APIKey, User, Organization
from app.models.schemas import MessageResponse
from app.api.v1.routes.profile import get_current_user


class APIKeyCreateRequest(BaseModel):
    name: Optional[str] = None

router = APIRouter(prefix="/settings", tags=["Settings"])

# Maximum number of API keys per user
MAX_API_KEYS_PER_USER = 5


def mask_api_key(key: str) -> str:
    """Mask API key for display (show first 8 and last 4 characters)."""
    if len(key) <= 12:
        return "*" * len(key)
    return f"{key[:8]}...{key[-4:]}"


@router.get("/api-keys")
def list_api_keys(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List all API keys for the current user.
    Returns masked keys for security.
    """
    # Get all API keys for this user
    api_keys = db.query(APIKey).filter(
        APIKey.user_id == current_user.id,
        APIKey.is_active == True
    ).order_by(APIKey.created_at.desc()).all()
    
    # Return masked keys
    result = []
    for key in api_keys:
        result.append({
            "id": str(key.id),
            "key": mask_api_key(key.key),
            "name": key.name,
            "is_active": key.is_active,
            "created_at": key.created_at.isoformat() if key.created_at else None,
            "last_used": key.last_used.isoformat() if key.last_used else None,
        })
    
    return result


@router.post("/api-keys")
def create_api_key(
    request: APIKeyCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a new API key for the current user.
    Maximum 5 keys per user.
    Returns the full key (only shown once).
    """
    # Check current key count
    key_count = db.query(APIKey).filter(
        APIKey.user_id == current_user.id,
        APIKey.is_active == True
    ).count()
    
    if key_count >= MAX_API_KEYS_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum of {MAX_API_KEYS_PER_USER} API keys allowed per user. Please delete an existing key first."
        )
    
    # Get user's organization (from first API key or organization membership)
    from app.models.database import OrganizationMember
    org_member = db.query(OrganizationMember).filter(
        OrganizationMember.user_id == current_user.id
    ).first()
    
    if not org_member:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is not associated with any organization"
        )
    
    organization_id = org_member.organization_id
    
    # Generate secure random API key
    api_key = secrets.token_urlsafe(32)
    
    # Create API key record
    db_key = APIKey(
        key=api_key,
        name=request.name,
        organization_id=organization_id,
        user_id=current_user.id,
        is_active=True
    )
    db.add(db_key)
    db.commit()
    db.refresh(db_key)
    
    # Return full key (only time it's shown)
    return {
        "id": str(db_key.id),
        "key": db_key.key,  # Full key shown only once
        "name": db_key.name,
        "is_active": db_key.is_active,
        "created_at": db_key.created_at.isoformat() if db_key.created_at else None,
        "last_used": None,
        "message": "Save this API key securely. You won't be able to see it again."
    }


@router.delete("/api-keys/{key_id}")
def delete_api_key(
    key_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete (deactivate) an API key.
    Only the owner can delete their own keys.
    """
    api_key = db.query(APIKey).filter(
        APIKey.id == key_id,
        APIKey.user_id == current_user.id
    ).first()
    
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found or you don't have permission to delete it"
        )
    
    # Deactivate instead of deleting (soft delete)
    api_key.is_active = False
    db.commit()
    
    return MessageResponse(message="API key deleted successfully")


@router.post("/api-keys/{key_id}/regenerate")
def regenerate_api_key(
    key_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Regenerate an API key.
    Creates a new key and deactivates the old one.
    Returns the new full key (only shown once).
    """
    old_key = db.query(APIKey).filter(
        APIKey.id == key_id,
        APIKey.user_id == current_user.id
    ).first()
    
    if not old_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found or you don't have permission to regenerate it"
        )
    
    # Check if we're at the limit (accounting for the key we're about to deactivate)
    key_count = db.query(APIKey).filter(
        APIKey.user_id == current_user.id,
        APIKey.is_active == True
    ).count()
    
    if key_count >= MAX_API_KEYS_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum of {MAX_API_KEYS_PER_USER} API keys allowed per user. Please delete an existing key first."
        )
    
    # Generate new secure random API key
    new_api_key = secrets.token_urlsafe(32)
    
    # Deactivate old key
    old_key.is_active = False
    
    # Create new API key with same organization and user
    new_db_key = APIKey(
        key=new_api_key,
        name=old_key.name,
        organization_id=old_key.organization_id,
        user_id=old_key.user_id,
        is_active=True
    )
    db.add(new_db_key)
    db.commit()
    db.refresh(new_db_key)
    
    # Return new full key (only time it's shown)
    return {
        "id": str(new_db_key.id),
        "key": new_db_key.key,  # Full key shown only once
        "name": new_db_key.name,
        "is_active": new_db_key.is_active,
        "created_at": new_db_key.created_at.isoformat() if new_db_key.created_at else None,
        "last_used": None,
        "message": "Save this API key securely. You won't be able to see it again."
    }

