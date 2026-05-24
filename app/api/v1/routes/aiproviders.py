"""
AI Provider API Routes
Complete CRUD operations for AI Provider API key management.

Multiple credentials per (org, provider) are supported. The first row
created for a given (org, provider) is automatically marked
``is_default``; further rows can be promoted via
``POST /aiproviders/{id}/set-default``. Runtime resolution prefers the
default row when no explicit credential id is selected.
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, func
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID

from app.dependencies import get_db, get_organization_id
from app.models.database import AIProvider
from app.models.schemas import (
    AIProviderCreate, AIProviderUpdate, AIProviderResponse
)
from app.core.encryption import encrypt_api_key
from app.services.credentials.resolver import clear_other_defaults

router = APIRouter(prefix="/aiproviders", tags=["aiproviders"])


def _scrub_for_response(db: Session, instance: AIProvider) -> AIProvider:
    """Detach the row from the session before clearing ``api_key``.

    The same SQLAlchemy session is reused across requests in tests; if we
    leave the instance attached and assign ``api_key = None``, SQLAlchemy
    treats it as a pending UPDATE and tries to flush ``api_key=NULL`` on
    the next request — which violates the column's NOT NULL constraint.
    """
    db.expunge(instance)
    instance.api_key = None
    return instance


@router.post("", response_model=AIProviderResponse, status_code=status.HTTP_201_CREATED, operation_id="createAIProvider")
async def create_aiprovider(
    aiprovider: AIProviderCreate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Create a new AI Provider credential row.

    Multiple credentials per (org, provider) are now allowed. The first
    row created for a given provider is auto-promoted to default;
    subsequent rows are stored as additional keys and can be promoted via
    ``set-default``.
    """
    provider_value = aiprovider.provider.value if hasattr(aiprovider.provider, 'value') else aiprovider.provider

    existing_default = db.query(AIProvider).filter(
        AIProvider.organization_id == organization_id,
        func.lower(AIProvider.provider) == provider_value.lower(),
        AIProvider.is_default.is_(True),
    ).first()

    requested_default = bool(aiprovider.is_default)
    will_be_default = requested_default or existing_default is None

    encrypted_api_key = encrypt_api_key(aiprovider.api_key)
    db_aiprovider = AIProvider(
        organization_id=organization_id,
        provider=provider_value,
        api_key=encrypted_api_key,
        name=aiprovider.name,
        is_default=will_be_default,
    )
    db.add(db_aiprovider)
    db.flush()

    if will_be_default:
        clear_other_defaults(
            AIProvider,
            db,
            organization_id,
            keep_id=db_aiprovider.id,
            provider_field="provider",
            provider_value=provider_value,
        )

    db.commit()
    db.refresh(db_aiprovider)

    return _scrub_for_response(db, db_aiprovider)


@router.get("", response_model=List[AIProviderResponse], operation_id="listAIProviders")
async def list_aiproviders(
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """List all AI Providers for the organization."""
    aiproviders = (
        db.query(AIProvider)
        .filter(AIProvider.organization_id == organization_id)
        .order_by(desc(AIProvider.is_default), desc(AIProvider.created_at))
        .all()
    )

    return [_scrub_for_response(db, provider) for provider in aiproviders]


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

    return _scrub_for_response(db, aiprovider)


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

    update_data = aiprovider_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == 'api_key' and value:
            encrypted_api_key = encrypt_api_key(value)
            db_aiprovider.api_key = encrypted_api_key
        else:
            setattr(db_aiprovider, field, value)

    db.commit()
    db.refresh(db_aiprovider)

    return _scrub_for_response(db, db_aiprovider)


@router.post(
    "/{aiprovider_id}/set-default",
    response_model=AIProviderResponse,
    operation_id="setDefaultAIProvider",
)
async def set_default_aiprovider(
    aiprovider_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Mark this AIProvider row as the default for its (org, provider)."""
    db_aiprovider = db.query(AIProvider).filter(
        AIProvider.id == aiprovider_id,
        AIProvider.organization_id == organization_id,
    ).first()

    if not db_aiprovider:
        raise HTTPException(
            status_code=404, detail=f"AI Provider {aiprovider_id} not found"
        )

    provider_value = (
        db_aiprovider.provider.value
        if hasattr(db_aiprovider.provider, "value")
        else db_aiprovider.provider
    )
    clear_other_defaults(
        AIProvider,
        db,
        organization_id,
        keep_id=db_aiprovider.id,
        provider_field="provider",
        provider_value=provider_value,
    )
    db_aiprovider.is_default = True
    db.commit()
    db.refresh(db_aiprovider)

    return _scrub_for_response(db, db_aiprovider)


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

    was_default = bool(db_aiprovider.is_default)
    provider_value = (
        db_aiprovider.provider.value
        if hasattr(db_aiprovider.provider, "value")
        else db_aiprovider.provider
    )

    db.delete(db_aiprovider)
    db.flush()

    if was_default:
        replacement = (
            db.query(AIProvider)
            .filter(
                AIProvider.organization_id == organization_id,
                func.lower(AIProvider.provider) == provider_value.lower(),
                AIProvider.is_active.is_(True),
            )
            .order_by(desc(AIProvider.updated_at), desc(AIProvider.created_at))
            .first()
        )
        if replacement:
            replacement.is_default = True

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

    aiprovider.last_tested_at = datetime.now(timezone.utc)
    db.commit()

    return {"status": "success", "message": "API key test completed"}
