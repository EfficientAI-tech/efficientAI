"""
Integrations API Routes
Manage integrations with external voice AI platforms (Retell, Vapi, etc.)
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from typing import List
from uuid import UUID
from loguru import logger

from app.dependencies import get_db, get_organization_id, get_api_key
from app.models.database import Integration, IntegrationPlatform, Agent
from app.models.schemas import (
    IntegrationCreate, IntegrationUpdate, IntegrationResponse
)
from app.core.encryption import encrypt_api_key, decrypt_api_key
from app.services.credentials.resolver import clear_other_defaults
from app.services.voice_providers import get_voice_provider

router = APIRouter(prefix="/integrations", tags=["Integrations"])


def _validate_smallest_connection(raw_api_key: str):
    """Validate a Smallest key via GET /atoms/v1/user."""
    try:
        provider_class = get_voice_provider(IntegrationPlatform.SMALLEST.value)
        provider = provider_class(api_key=raw_api_key)
        provider.test_connection()
        if hasattr(provider, "get_user_details"):
            return provider.get_user_details()
        return None
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Smallest API key validation failed: {str(e)}"
        )


@router.post("", response_model=IntegrationResponse, status_code=status.HTTP_201_CREATED, operation_id="createIntegration")
async def create_integration(
    integration_data: IntegrationCreate,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """Create a new credential row for a voice AI platform.

    Multiple credentials per platform are now supported. The first row
    created for a given (org, platform) automatically becomes the
    default; subsequent rows can be promoted via
    ``POST /integrations/{id}/set-default``. ``integration_data.is_default``
    can also be set explicitly to mark the new row as the default at
    creation time.
    Requires at least WRITER role.
    """
    from sqlalchemy import func
    platform_value = integration_data.platform.value if hasattr(integration_data.platform, 'value') else integration_data.platform

    user_details = None
    if platform_value.lower() == IntegrationPlatform.SMALLEST.value:
        user_details = _validate_smallest_connection(integration_data.api_key)

    encrypted_api_key = encrypt_api_key(integration_data.api_key)
    integration_name = integration_data.name
    if not integration_name and isinstance(user_details, dict):
        email = user_details.get("email") or user_details.get("userEmail")
        if email:
            integration_name = f"Smallest ({email})"

    existing_default = db.query(Integration).filter(
        Integration.organization_id == organization_id,
        func.lower(Integration.platform) == platform_value.lower(),
        Integration.is_default.is_(True),
        Integration.is_active.is_(True),
    ).first()

    requested_default = bool(integration_data.is_default)
    will_be_default = requested_default or existing_default is None

    integration = Integration(
        organization_id=organization_id,
        platform=platform_value,
        name=integration_name,
        api_key=encrypted_api_key,
        public_key=integration_data.public_key,
        is_active=True,
        is_default=will_be_default,
        last_tested_at=datetime.now(timezone.utc) if user_details is not None else None,
    )

    db.add(integration)
    db.flush()

    if will_be_default:
        clear_other_defaults(
            Integration,
            db,
            organization_id,
            keep_id=integration.id,
            provider_field="platform",
            provider_value=platform_value,
        )

    db.commit()
    db.refresh(integration)

    return integration


@router.post(
    "/{integration_id}/set-default",
    response_model=IntegrationResponse,
    operation_id="setDefaultIntegration",
)
async def set_default_integration(
    integration_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Mark this integration as the default for its (org, platform).

    Atomically clears the default flag on every other row for the same
    (org, platform) so the partial unique index in migration 028 holds.
    """
    integration = db.query(Integration).filter(
        Integration.id == integration_id,
        Integration.organization_id == organization_id,
    ).first()

    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    if not integration.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot mark an inactive integration as default",
        )

    platform_value = (
        integration.platform.value
        if hasattr(integration.platform, "value")
        else integration.platform
    )

    clear_other_defaults(
        Integration,
        db,
        organization_id,
        keep_id=integration.id,
        provider_field="platform",
        provider_value=platform_value,
    )
    integration.is_default = True
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

    valid_platforms = {p.value for p in IntegrationPlatform}
    filtered_integrations: List[Integration] = []
    for integration in integrations:
        raw_platform = (
            integration.platform.value
            if hasattr(integration.platform, "value")
            else str(integration.platform).lower()
        )
        if raw_platform in valid_platforms:
            filtered_integrations.append(integration)
        else:
            logger.warning(
                "Skipping integration {} with invalid platform '{}'",
                integration.id,
                integration.platform,
            )

    return filtered_integrations


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

    raw_platform = (
        integration.platform.value
        if hasattr(integration.platform, "value")
        else str(integration.platform).lower()
    )
    if raw_platform not in {p.value for p in IntegrationPlatform}:
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
        platform_value = integration.platform.value if hasattr(integration.platform, 'value') else integration.platform
        if platform_value.lower() == IntegrationPlatform.SMALLEST.value:
            _validate_smallest_connection(integration_update.api_key)
            integration.last_tested_at = datetime.now(timezone.utc)
        integration.api_key = encrypt_api_key(integration_update.api_key)
    
    if integration_update.public_key is not None:
        integration.public_key = integration_update.public_key
    
    if integration_update.is_active is not None:
        integration.is_active = integration_update.is_active
    
    db.commit()
    db.refresh(integration)
    
    return integration


@router.delete("/{integration_id}", operation_id="deleteIntegration")
async def delete_integration(
    integration_id: UUID,
    force: bool = Query(False, description="Force delete and unlink all agents using this integration"),
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """
    Delete an integration. Returns 409 if agents are using it unless force=true.
    Requires at least WRITER role.
    """
    integration = db.query(Integration).filter(
        Integration.id == integration_id,
        Integration.organization_id == organization_id
    ).first()

    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    agents_count = db.query(Agent).filter(
        Agent.voice_ai_integration_id == integration_id,
        Agent.organization_id == organization_id,
    ).count()

    dependencies = {}
    if agents_count > 0:
        dependencies["agents"] = agents_count

    if dependencies and not force:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": f"Cannot delete integration. It is used by {agents_count} agent(s).",
                "dependencies": dependencies,
                "hint": "Use force=true to delete this integration and unlink all agents.",
            },
        )

    if dependencies:
        db.query(Agent).filter(
            Agent.voice_ai_integration_id == integration_id,
            Agent.organization_id == organization_id,
        ).update(
            {Agent.voice_ai_integration_id: None, Agent.voice_ai_agent_id: None},
            synchronize_session=False,
        )

    was_default = bool(integration.is_default)
    platform_value = (
        integration.platform.value
        if hasattr(integration.platform, "value")
        else integration.platform
    )
    db.delete(integration)
    db.flush()

    # If we just removed the default credential, promote the next active
    # row (most recently updated) so resolution-by-default keeps working.
    if was_default:
        from sqlalchemy import func, desc
        replacement = (
            db.query(Integration)
            .filter(
                Integration.organization_id == organization_id,
                func.lower(Integration.platform) == platform_value.lower(),
                Integration.is_active.is_(True),
            )
            .order_by(desc(Integration.updated_at), desc(Integration.created_at))
            .first()
        )
        if replacement:
            replacement.is_default = True

    db.commit()

    if dependencies:
        return JSONResponse(
            status_code=200,
            content={
                "message": "Integration deleted and agents unlinked successfully.",
                "deleted": dependencies,
            },
        )

    return JSONResponse(status_code=204, content=None)

@router.get("/{integration_id}/api-key")
async def get_integration_api_key(
    integration_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """
    Get the decrypted API key for an integration.
    This endpoint is used for client-side operations like web calls.
    Requires at least READER role.
    """
    integration = db.query(Integration).filter(
        Integration.id == integration_id,
        Integration.organization_id == organization_id,
        Integration.is_active == True
    ).first()
    
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found or inactive")
    
    # Only allow for Retell and Vapi platforms (for web calls)
    if integration.platform not in [IntegrationPlatform.RETELL, IntegrationPlatform.VAPI]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="API key retrieval is only available for Retell and Vapi integrations"
        )
    
    try:
        decrypted_api_key = decrypt_api_key(integration.api_key)
        return {
            "api_key": decrypted_api_key,
            "public_key": integration.public_key
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to decrypt API key: {str(e)}"
        )
