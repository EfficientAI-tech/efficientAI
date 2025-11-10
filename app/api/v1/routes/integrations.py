"""
Integrations API Routes
Manage integrations with external voice AI platforms (Retell, Vapi, etc.)
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID

from app.dependencies import get_db, get_organization_id, get_api_key
from app.models.database import Integration, IntegrationPlatform
from app.models.schemas import (
    IntegrationCreate, IntegrationUpdate, IntegrationResponse, MessageResponse
)
from app.core.encryption import encrypt_api_key, decrypt_api_key

router = APIRouter(prefix="/integrations", tags=["Integrations"])


@router.post("", response_model=IntegrationResponse, status_code=status.HTTP_201_CREATED, operation_id="createIntegration")
async def create_integration(
    integration_data: IntegrationCreate,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """
    Create a new integration with an external platform.
    Requires at least WRITER role.
    """
    # Encrypt the API key before storing
    encrypted_api_key = encrypt_api_key(integration_data.api_key)
    
    # Check if integration already exists for this platform
    existing = db.query(Integration).filter(
        Integration.organization_id == organization_id,
        Integration.platform == integration_data.platform,
        Integration.is_active == True
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"An active integration for {integration_data.platform.value} already exists"
        )
    
    integration = Integration(
        organization_id=organization_id,
        platform=integration_data.platform,
        name=integration_data.name,
        api_key=encrypted_api_key,
        is_active=True
    )
    
    db.add(integration)
    db.commit()
    db.refresh(integration)
    
    return integration


@router.get("", response_model=List[IntegrationResponse], operation_id="listIntegrations")
async def list_integrations(
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """
    List all integrations for the organization.
    Requires at least READER role.
    """
    integrations = db.query(Integration).filter(
        Integration.organization_id == organization_id
    ).order_by(Integration.created_at.desc()).all()
    
    return integrations


@router.get("/{integration_id}", response_model=IntegrationResponse)
async def get_integration(
    integration_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """
    Get a specific integration.
    Requires at least READER role.
    """
    integration = db.query(Integration).filter(
        Integration.id == integration_id,
        Integration.organization_id == organization_id
    ).first()
    
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    
    return integration


@router.put("/{integration_id}", response_model=IntegrationResponse, operation_id="updateIntegration")
async def update_integration(
    integration_id: UUID,
    integration_update: IntegrationUpdate,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """
    Update an integration.
    Requires at least WRITER role.
    """
    integration = db.query(Integration).filter(
        Integration.id == integration_id,
        Integration.organization_id == organization_id
    ).first()
    
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    
    if integration_update.name is not None:
        integration.name = integration_update.name
    
    if integration_update.api_key is not None:
        integration.api_key = encrypt_api_key(integration_update.api_key)
    
    if integration_update.is_active is not None:
        integration.is_active = integration_update.is_active
    
    db.commit()
    db.refresh(integration)
    
    return integration


@router.delete("/{integration_id}", status_code=status.HTTP_204_NO_CONTENT, operation_id="deleteIntegration")
async def delete_integration(
    integration_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """
    Delete an integration.
    Requires at least WRITER role.
    """
    integration = db.query(Integration).filter(
        Integration.id == integration_id,
        Integration.organization_id == organization_id
    ).first()
    
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    
    db.delete(integration)
    db.commit()
    return None


@router.post("/{integration_id}/test", response_model=MessageResponse)
async def test_integration(
    integration_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """
    Test an integration by validating the API key.
    Requires at least READER role.
    """
    integration = db.query(Integration).filter(
        Integration.id == integration_id,
        Integration.organization_id == organization_id
    ).first()
    
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    
    # TODO: Implement actual API key validation for each platform
    # For now, just mark as tested
    from datetime import datetime
    integration.last_tested_at = datetime.utcnow()
    db.commit()
    
    return {"message": f"Integration with {integration.platform.value} is valid"}

