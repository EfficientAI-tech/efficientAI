"""
Per-organization LLM gateway settings.

Backed by ``organizations.llm_gateway_settings`` JSON.
Virtual keys and LiteLLM proxy master keys are encrypted at rest.
"""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.database import Organization
from app.services.ai.llm_gateway import (
    EffectiveRouting,
    GatewayType,
    _platform_config,
    gateway_managed_credentials_enabled,
    normalize_bifrost_url,
    normalize_litellm_proxy_url,
    resolve_llm_gateway,
)

GatewayMode = Literal["inherit", "enabled", "disabled"]
GatewayTypeOverride = Literal["inherit", "bifrost", "litellm_proxy"]


def _mode_from_enabled(enabled: Any) -> GatewayMode:
    if enabled is True:
        return "enabled"
    if enabled is False:
        return "disabled"
    return "inherit"


def _enabled_from_mode(mode: GatewayMode) -> Optional[bool]:
    if mode == "enabled":
        return True
    if mode == "disabled":
        return False
    return None


def _gateway_type_from_stored(raw: Dict[str, Any]) -> GatewayTypeOverride:
    stored = raw.get("gateway_type")
    if stored in ("bifrost", "litellm_proxy"):
        return stored
    return "inherit"


def _effective_routing(resolved: Any) -> EffectiveRouting:
    if resolved is None:
        return "direct"
    return resolved.gateway_type


def _normalize_url_for_type(base_url: str, gateway_type: GatewayType) -> str:
    if gateway_type == "bifrost":
        return normalize_bifrost_url(base_url)
    return normalize_litellm_proxy_url(base_url)


def _resolve_effective_gateway_type(
    org_raw: Dict[str, Any], platform: Dict[str, Any]
) -> GatewayType:
    org_type = org_raw.get("gateway_type")
    if org_type in ("bifrost", "litellm_proxy"):
        return org_type
    platform_type = platform.get("gateway_type", "bifrost")
    if platform_type in ("bifrost", "litellm_proxy"):
        return platform_type
    return "bifrost"


def get_org_settings(organization_id: UUID, db: Session) -> Dict[str, Any]:
    """Return stored org settings merged with effective resolved routing."""
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    raw = (org.llm_gateway_settings or {}) if org else {}

    mode = _mode_from_enabled(raw.get("enabled"))
    stored_base_url = raw.get("base_url")
    has_virtual_key = bool(raw.get("virtual_key"))
    has_master_key = bool(raw.get("master_key"))
    gateway_type = _gateway_type_from_stored(raw)

    resolved = resolve_llm_gateway(organization_id, db)
    platform = _platform_config()
    effective_type = _resolve_effective_gateway_type(raw, platform)

    return {
        "mode": mode,
        "gateway_type": gateway_type,
        "base_url": stored_base_url,
        "has_virtual_key": has_virtual_key,
        "has_master_key": has_master_key,
        "platform_enabled": platform["enabled"],
        "platform_gateway_type": platform["gateway_type"],
        "platform_base_url": platform["base_url"],
        "effective_routing": _effective_routing(resolved),
        "effective_gateway_type": effective_type if resolved else None,
        "effective_base_url": resolved.api_base if resolved else None,
        "effective_has_virtual_key": bool(resolved and resolved.virtual_key),
        "effective_has_master_key": bool(resolved and resolved.master_key),
        "gateway_managed_credentials": gateway_managed_credentials_enabled(),
    }


def set_org_settings(
    organization_id: UUID,
    db: Session,
    *,
    mode: GatewayMode,
    gateway_type: GatewayTypeOverride = "inherit",
    base_url: Optional[str] = None,
    virtual_key: Optional[str] = None,
    master_key: Optional[str] = None,
    clear_virtual_key: bool = False,
    clear_master_key: bool = False,
) -> Dict[str, Any]:
    """Validate and persist org-level LLM gateway overrides."""
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    existing = dict(org.llm_gateway_settings or {})
    platform = _platform_config()
    payload: Dict[str, Any] = {
        "enabled": _enabled_from_mode(mode),
    }

    if gateway_type == "inherit":
        payload["gateway_type"] = None
    else:
        payload["gateway_type"] = gateway_type

    effective_type_for_validation: GatewayType
    if gateway_type in ("bifrost", "litellm_proxy"):
        effective_type_for_validation = gateway_type
    else:
        effective_type_for_validation = _resolve_effective_gateway_type({}, platform)

    if base_url is not None:
        trimmed = base_url.strip()
        if trimmed:
            try:
                _normalize_url_for_type(trimmed, effective_type_for_validation)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            payload["base_url"] = trimmed
        else:
            payload["base_url"] = None
    elif "base_url" in existing:
        payload["base_url"] = existing.get("base_url")

    if clear_virtual_key:
        payload["virtual_key"] = None
    elif virtual_key is not None:
        trimmed_key = virtual_key.strip()
        if trimmed_key:
            from app.core.encryption import encrypt_api_key

            payload["virtual_key"] = encrypt_api_key(trimmed_key)
        else:
            payload["virtual_key"] = None
    elif "virtual_key" in existing:
        payload["virtual_key"] = existing.get("virtual_key")

    if clear_master_key:
        payload["master_key"] = None
    elif master_key is not None:
        trimmed_key = master_key.strip()
        if trimmed_key:
            from app.core.encryption import encrypt_api_key

            payload["master_key"] = encrypt_api_key(trimmed_key)
        else:
            payload["master_key"] = None
    elif "master_key" in existing:
        payload["master_key"] = existing.get("master_key")

    org.llm_gateway_settings = payload
    db.commit()

    return get_org_settings(organization_id, db)
