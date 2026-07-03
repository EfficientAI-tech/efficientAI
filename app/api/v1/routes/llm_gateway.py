"""Organization-level LLM gateway settings."""

from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_organization_id
from app.services.ai.llm_gateway_settings import (
    GatewayMode,
    GatewayTypeOverride,
    get_org_settings,
    set_org_settings,
)

router = APIRouter(prefix="/organizations/llm-gateway", tags=["LLM Gateway"])


class LLMGatewaySettingsResponse(BaseModel):
    mode: GatewayMode
    gateway_type: GatewayTypeOverride
    base_url: Optional[str] = None
    has_virtual_key: bool = False
    has_master_key: bool = False
    platform_enabled: bool = False
    platform_gateway_type: Literal["bifrost", "litellm_proxy"] = "bifrost"
    platform_base_url: Optional[str] = None
    effective_routing: Literal["direct", "bifrost", "litellm_proxy"]
    effective_gateway_type: Optional[Literal["bifrost", "litellm_proxy"]] = None
    effective_base_url: Optional[str] = None
    effective_has_virtual_key: bool = False
    effective_has_master_key: bool = False
    gateway_managed_credentials: bool = False


class LLMGatewaySettingsUpdate(BaseModel):
    mode: GatewayMode = Field(
        ...,
        description="inherit: use platform default; enabled: force gateway; disabled: opt out",
    )
    gateway_type: GatewayTypeOverride = Field(
        default="inherit",
        description="inherit: use platform gateway type; bifrost or litellm_proxy to override",
    )
    base_url: Optional[str] = Field(
        default=None,
        description="Optional org-specific gateway URL override.",
    )
    virtual_key: Optional[str] = Field(
        default=None,
        description="Optional Bifrost virtual key (x-bf-vk). Omit to keep existing.",
    )
    master_key: Optional[str] = Field(
        default=None,
        description="Optional LiteLLM Proxy master key. Omit to keep existing.",
    )
    clear_virtual_key: bool = Field(
        default=False,
        description="When true, remove the stored org virtual key.",
    )
    clear_master_key: bool = Field(
        default=False,
        description="When true, remove the stored org master key.",
    )


@router.get("", response_model=LLMGatewaySettingsResponse)
def get_llm_gateway_settings(
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    return LLMGatewaySettingsResponse(**get_org_settings(organization_id, db))


@router.put("", response_model=LLMGatewaySettingsResponse)
def update_llm_gateway_settings(
    body: LLMGatewaySettingsUpdate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    result = set_org_settings(
        organization_id,
        db,
        mode=body.mode,
        gateway_type=body.gateway_type,
        base_url=body.base_url,
        virtual_key=body.virtual_key,
        master_key=body.master_key,
        clear_virtual_key=body.clear_virtual_key,
        clear_master_key=body.clear_master_key,
    )
    return LLMGatewaySettingsResponse(**result)
