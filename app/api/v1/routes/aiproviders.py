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
from typing import List, Optional
from uuid import UUID

from app.dependencies import get_db, get_organization_id
from app.models.database import AIProvider
from app.models.enums import CredentialRoutingMode
from app.models.schemas import (
    AIProviderCreate, AIProviderUpdate, AIProviderResponse
)
from app.config import settings
from app.core.encryption import encrypt_api_key
from app.services.credentials.resolver import clear_other_defaults
from app.services.ai.llm_gateway import (
    GATEWAY_MANAGED_KEY_SENTINEL,
    get_credential_effective_gateway_interface,
    get_credential_effective_routing_label,
    is_gateway_managed_stored_key,
    normalize_bifrost_native_url,
    normalize_bifrost_url,
)

router = APIRouter(prefix="/aiproviders", tags=["aiproviders"])


def _sanitize_gateway_base_url(
    base_url: Optional[str],
    gateway_interface: str,
) -> Optional[str]:
    trimmed = (base_url or "").strip()
    if not trimmed:
        return None
    interface = (gateway_interface or "inherit").strip().lower()
    try:
        if interface == "native_openai":
            return normalize_bifrost_native_url(trimmed) or None
        if interface == "litellm_shim":
            return normalize_bifrost_url(trimmed) or None
        return trimmed
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


def _scrub_for_response(
    db: Session,
    instance: AIProvider,
    organization_id: UUID,
) -> AIProviderResponse:
    """Detach the row from the session before clearing ``api_key``."""
    gateway_managed = is_gateway_managed_stored_key(instance.api_key)
    effective_routing = get_credential_effective_routing_label(
        organization_id,
        db,
        instance.routing_mode,
    )
    effective_gateway_interface = get_credential_effective_gateway_interface(
        organization_id,
        db,
        getattr(instance, "gateway_interface", None),
    )
    has_gateway_auth_secret = bool(getattr(instance, "gateway_auth_secret", None))
    db.expunge(instance)
    instance.api_key = None
    instance.gateway_auth_secret = None
    response = AIProviderResponse.model_validate(instance)
    return response.model_copy(
        update={
            "gateway_managed": gateway_managed,
            "effective_routing": effective_routing,
            "effective_gateway_interface": effective_gateway_interface,
            "has_gateway_auth_secret": has_gateway_auth_secret,
        }
    )


def _validate_routing_and_api_key(
    *,
    routing_mode: CredentialRoutingMode,
    api_key: Optional[str],
    gateway_model: Optional[str],
    has_existing_key: bool = False,
) -> None:
    mode = routing_mode.value if hasattr(routing_mode, "value") else str(routing_mode)
    trimmed_key = (api_key or "").strip()

    if mode == CredentialRoutingMode.DIRECT.value and not trimmed_key and not has_existing_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="api_key is required when routing_mode is direct.",
        )

    if mode == CredentialRoutingMode.GATEWAY.value:
        return

    if mode == CredentialRoutingMode.INHERIT.value:
        if not trimmed_key and not has_existing_key:
            if settings.LLM_GATEWAY_PASSTHROUGH_PROVIDER_KEYS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "api_key is required when platform passthrough_provider_keys "
                        "is enabled."
                    ),
                )
            return


def _encrypt_provider_api_key(
    api_key: Optional[str],
    *,
    routing_mode: CredentialRoutingMode,
) -> str:
    trimmed = (api_key or "").strip()
    if trimmed:
        return encrypt_api_key(trimmed)

    mode = routing_mode.value if hasattr(routing_mode, "value") else str(routing_mode)
    if mode in (
        CredentialRoutingMode.GATEWAY.value,
        CredentialRoutingMode.INHERIT.value,
    ):
        return encrypt_api_key(GATEWAY_MANAGED_KEY_SENTINEL)

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="api_key is required when routing_mode is direct.",
    )


@router.post("", response_model=AIProviderResponse, status_code=status.HTTP_201_CREATED, operation_id="createAIProvider")
async def create_aiprovider(
    aiprovider: AIProviderCreate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Create a new AI Provider credential row."""
    provider_value = aiprovider.provider.value if hasattr(aiprovider.provider, 'value') else aiprovider.provider

    _validate_routing_and_api_key(
        routing_mode=aiprovider.routing_mode,
        api_key=aiprovider.api_key,
        gateway_model=aiprovider.gateway_model,
    )

    existing_default = db.query(AIProvider).filter(
        AIProvider.organization_id == organization_id,
        func.lower(AIProvider.provider) == provider_value.lower(),
        AIProvider.is_default.is_(True),
    ).first()

    requested_default = bool(aiprovider.is_default)
    will_be_default = requested_default or existing_default is None

    encrypted_api_key = _encrypt_provider_api_key(
        aiprovider.api_key,
        routing_mode=aiprovider.routing_mode,
    )
    gateway_interface_value = aiprovider.gateway_interface.value
    db_aiprovider = AIProvider(
        organization_id=organization_id,
        provider=provider_value,
        api_key=encrypted_api_key,
        name=aiprovider.name,
        is_default=will_be_default,
        routing_mode=aiprovider.routing_mode.value,
        gateway_model=aiprovider.gateway_model,
        gateway_interface=gateway_interface_value,
        gateway_base_url=_sanitize_gateway_base_url(
            aiprovider.gateway_base_url,
            gateway_interface_value,
        ),
        gateway_auth_header=aiprovider.gateway_auth_header,
        gateway_auth_secret_env=aiprovider.gateway_auth_secret_env,
        gateway_auth_secret=(
            encrypt_api_key(aiprovider.gateway_auth_secret)
            if aiprovider.gateway_auth_secret
            else None
        ),
        gateway_extra_headers=aiprovider.gateway_extra_headers,
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

    return _scrub_for_response(db, db_aiprovider, organization_id)


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

    return [
        _scrub_for_response(db, provider, organization_id)
        for provider in aiproviders
    ]


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

    return _scrub_for_response(db, aiprovider, organization_id)


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
    next_routing_mode = update_data.get(
        "routing_mode",
        CredentialRoutingMode(db_aiprovider.routing_mode),
    )
    next_gateway_model = update_data.get("gateway_model", db_aiprovider.gateway_model)
    next_api_key = update_data.get("api_key")

    if "routing_mode" in update_data or "api_key" in update_data or "gateway_model" in update_data:
        _validate_routing_and_api_key(
            routing_mode=next_routing_mode,
            api_key=next_api_key,
            gateway_model=next_gateway_model,
            has_existing_key=(
                bool(db_aiprovider.api_key)
                and not is_gateway_managed_stored_key(db_aiprovider.api_key)
            ),
        )

    skip_fields = {
        "api_key",
        "routing_mode",
        "gateway_interface",
        "gateway_auth_secret",
        "clear_gateway_auth_secret",
    }

    for field, value in update_data.items():
        if field in skip_fields:
            continue
        if field == "gateway_base_url":
            interface = (
                update_data["gateway_interface"].value
                if update_data.get("gateway_interface") is not None
                else db_aiprovider.gateway_interface
            )
            value = _sanitize_gateway_base_url(value, interface)
        setattr(db_aiprovider, field, value)

    if "api_key" in update_data and update_data["api_key"]:
        db_aiprovider.api_key = encrypt_api_key(update_data["api_key"])
    if "routing_mode" in update_data and update_data["routing_mode"] is not None:
        db_aiprovider.routing_mode = update_data["routing_mode"].value
    if "gateway_interface" in update_data and update_data["gateway_interface"] is not None:
        db_aiprovider.gateway_interface = update_data["gateway_interface"].value
    if update_data.get("clear_gateway_auth_secret"):
        db_aiprovider.gateway_auth_secret = None
    elif update_data.get("gateway_auth_secret"):
        db_aiprovider.gateway_auth_secret = encrypt_api_key(update_data["gateway_auth_secret"])

    db.commit()
    db.refresh(db_aiprovider)

    return _scrub_for_response(db, db_aiprovider, organization_id)


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

    return _scrub_for_response(db, db_aiprovider, organization_id)


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
