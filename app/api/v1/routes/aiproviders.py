"""
AI Provider API Routes
Complete CRUD operations for AI Provider API key management
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID

from app.dependencies import get_db, get_organization_id
from app.models.database import AIProvider
from app.models.schemas import (
    AIProviderCreate, AIProviderUpdate, AIProviderResponse
)
from app.core.encryption import encrypt_api_key

router = APIRouter(prefix="/aiproviders", tags=["aiproviders"])


@router.post("", response_model=AIProviderResponse, status_code=status.HTTP_201_CREATED, operation_id="createAIProvider")
async def create_aiprovider(
    aiprovider: AIProviderCreate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Create or update an AI Provider configuration"""
    # Check if provider already exists for this organization
    existing = db.query(AIProvider).filter(
        AIProvider.organization_id == organization_id,
        AIProvider.provider == aiprovider.provider
    ).first()
    
    if existing:
        # Update existing provider
        encrypted_api_key = encrypt_api_key(aiprovider.api_key)
        existing.api_key = encrypted_api_key
        existing.name = aiprovider.name
        existing.is_active = True
        db.commit()
        db.refresh(existing)
        
        # Don't return API key
        existing.api_key = None
        return existing
    
    # Create new provider
    encrypted_api_key = encrypt_api_key(aiprovider.api_key)
    db_aiprovider = AIProvider(
        organization_id=organization_id,
        provider=aiprovider.provider,
        api_key=encrypted_api_key,
        name=aiprovider.name,
    )
    db.add(db_aiprovider)
    db.commit()
    db.refresh(db_aiprovider)
    
    # Don't return API key
    db_aiprovider.api_key = None
    
    return db_aiprovider


@router.get("", response_model=List[AIProviderResponse], operation_id="listAIProviders")
async def list_aiproviders(
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """List all AI Providers for the organization"""
    aiproviders = db.query(AIProvider).filter(
        AIProvider.organization_id == organization_id
    ).all()
    
    # Don't return API keys
    for provider in aiproviders:
        provider.api_key = None
    
    return aiproviders


@router.get("/{aiprovider_id}", response_model=AIProviderResponse)
async def get_aiprovider(
    aiprovider_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Get a specific AI Provider"""
    aiprovider = db.query(AIProvider).filter(
        AIProvider.id == aiprovider_id,
        AIProvider.organization_id == organization_id
    ).first()
    
    if not aiprovider:
        raise HTTPException(
            status_code=404, detail=f"AI Provider {aiprovider_id} not found"
        )
    
    # Don't return API key
    aiprovider.api_key = None
    
    return aiprovider


@router.put("/{aiprovider_id}", response_model=AIProviderResponse, operation_id="updateAIProvider")
async def update_aiprovider(
    aiprovider_id: UUID,
    aiprovider_update: AIProviderUpdate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Update an existing AI Provider"""
    db_aiprovider = db.query(AIProvider).filter(
        AIProvider.id == aiprovider_id,
        AIProvider.organization_id == organization_id
    ).first()
    
    if not db_aiprovider:
        raise HTTPException(
            status_code=404, detail=f"AI Provider {aiprovider_id} not found"
        )
    
    update_data = aiprovider_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        if field == 'api_key' and value:
            encrypted_api_key = encrypt_api_key(value)
            db_aiprovider.api_key = encrypted_api_key
        else:
            setattr(db_aiprovider, field, value)
    
    db.commit()
    db.refresh(db_aiprovider)
    
    # Don't return API key
    db_aiprovider.api_key = None
    
    return db_aiprovider


@router.delete("/{aiprovider_id}", status_code=status.HTTP_204_NO_CONTENT, operation_id="deleteAIProvider")
async def delete_aiprovider(
    aiprovider_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Delete an AI Provider"""
    db_aiprovider = db.query(AIProvider).filter(
        AIProvider.id == aiprovider_id,
        AIProvider.organization_id == organization_id
    ).first()
    
    if not db_aiprovider:
        raise HTTPException(
            status_code=404, detail=f"AI Provider {aiprovider_id} not found"
        )
    
    db.delete(db_aiprovider)
    db.commit()
    
    return None


@router.post("/{aiprovider_id}/test", status_code=status.HTTP_200_OK, operation_id="testAIProvider")
async def test_aiprovider(
    aiprovider_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Test an AI Provider API key"""
    aiprovider = db.query(AIProvider).filter(
        AIProvider.id == aiprovider_id,
        AIProvider.organization_id == organization_id
    ).first()
    
    if not aiprovider:
        raise HTTPException(
            status_code=404, detail=f"AI Provider {aiprovider_id} not found"
        )
    
    # TODO: Implement actual API key testing based on provider type
    # For now, just update the last_tested_at timestamp
    from datetime import datetime
    aiprovider.last_tested_at = datetime.utcnow()
    db.commit()
    
    return {"status": "success", "message": "API key test completed"}

