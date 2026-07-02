"""
LLM gateway resolver for batch/eval LiteLLM workloads.

Supports Bifrost (/litellm proxy) and self-hosted LiteLLM Proxy gateways.
Platform defaults live in ``config.yml``; per-org overrides are stored in
``organizations.llm_gateway_settings`` JSON.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional
from urllib.parse import urlparse
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.config import settings


GatewayType = Literal["bifrost", "litellm_proxy"]
EffectiveRouting = Literal["direct", "bifrost", "litellm_proxy"]

# Backward-compatible alias used by stored AI provider credentials.
GATEWAY_MANAGED_KEY_SENTINEL = "__bifrost_gateway_managed__"
# LiteLLM's OpenAI client path requires a non-empty api_key even when
# api_base points at a gateway. Gateways authenticate via headers or master keys.
LITELLM_GATEWAY_PLACEHOLDER_API_KEY = "gateway-managed"


def gateway_managed_credentials_enabled() -> bool:
    """True when the platform expects provider keys to live in the gateway only."""
    return not bool(settings.LLM_GATEWAY_PASSTHROUGH_PROVIDER_KEYS)


def is_gateway_managed_stored_key(encrypted_api_key: str) -> bool:
    """Return True when the stored credential is the gateway-managed placeholder."""
    try:
        from app.core.encryption import decrypt_api_key

        return decrypt_api_key(encrypted_api_key) == GATEWAY_MANAGED_KEY_SENTINEL
    except Exception:
        return False


def resolve_litellm_api_key(
    organization_id: UUID,
    db: Session,
    ai_provider: Any,
) -> Optional[str]:
    """Decrypt the org credential, or return None when the gateway supplies the key."""
    from app.core.encryption import decrypt_api_key

    try:
        raw_key = decrypt_api_key(ai_provider.api_key)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to decrypt API key for provider {ai_provider.provider}: {exc}"
        ) from exc

    if raw_key != GATEWAY_MANAGED_KEY_SENTINEL:
        return raw_key

    gateway = resolve_llm_gateway(organization_id, db)
    if gateway and not gateway.passthrough_provider_keys:
        return None

    raise RuntimeError(
        "AI provider is configured for gateway-managed credentials, "
        "but the LLM gateway is not active for this organization. "
        "Enable the LLM Gateway or add a provider API key."
    )


@dataclass(frozen=True)
class LLMGatewayConfig:
    """Resolved gateway settings for a single LiteLLM call."""

    gateway_type: GatewayType
    api_base: str
    virtual_key: Optional[str] = None
    master_key: Optional[str] = None
    passthrough_provider_keys: bool = True


def normalize_bifrost_url(base_url: str) -> str:
    """Ensure the Bifrost LiteLLM proxy URL is well-formed."""
    url = (base_url or "").strip().rstrip("/")
    if not url:
        return ""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(
            "Bifrost base_url must be an absolute URL including scheme and host "
            "(e.g. http://localhost:8080/litellm)."
        )
    if not url.endswith("/litellm"):
        logger.warning(
            "Bifrost base_url '{}' does not end with '/litellm'; appending suffix.",
            url,
        )
        url = f"{url}/litellm"
    return url


def normalize_litellm_proxy_url(base_url: str) -> str:
    """Ensure a LiteLLM Proxy URL is well-formed."""
    url = (base_url or "").strip().rstrip("/")
    if not url:
        return ""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(
            "LiteLLM proxy base_url must be an absolute URL including scheme and host "
            "(e.g. http://localhost:4000)."
        )
    return url


def _normalize_base_url(base_url: str, gateway_type: GatewayType) -> str:
    if gateway_type == "bifrost":
        return normalize_bifrost_url(base_url)
    return normalize_litellm_proxy_url(base_url)


def _platform_config() -> Dict[str, Any]:
    gateway_type = (settings.LLM_GATEWAY_TYPE or "bifrost").strip().lower()
    if gateway_type not in ("bifrost", "litellm_proxy"):
        gateway_type = "bifrost"
    return {
        "enabled": bool(settings.LLM_GATEWAY_ENABLED),
        "gateway_type": gateway_type,
        "base_url": (settings.LLM_GATEWAY_BASE_URL or "").strip() or None,
        "virtual_key": (settings.LLM_GATEWAY_VIRTUAL_KEY or "").strip() or None,
        "master_key": (settings.LLM_GATEWAY_MASTER_KEY or "").strip() or None,
        "passthrough_provider_keys": bool(settings.LLM_GATEWAY_PASSTHROUGH_PROVIDER_KEYS),
    }


def _get_org_raw_settings(organization_id: UUID, db: Session) -> Dict[str, Any]:
    from app.models.database import Organization

    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        return {}
    raw = org.llm_gateway_settings
    return dict(raw) if isinstance(raw, dict) else {}


def _decrypt_org_secret(raw: Dict[str, Any], field: str) -> Optional[str]:
    encrypted = raw.get(field)
    if not encrypted:
        return None
    try:
        from app.core.encryption import decrypt_api_key

        return decrypt_api_key(encrypted)
    except Exception as exc:
        logger.warning("Failed to decrypt org LLM gateway {}: {}", field, exc)
        return None


def _decrypt_org_virtual_key(raw: Dict[str, Any]) -> Optional[str]:
    return _decrypt_org_secret(raw, "virtual_key")


def _decrypt_org_master_key(raw: Dict[str, Any]) -> Optional[str]:
    return _decrypt_org_secret(raw, "master_key")


def _resolve_gateway_type(org: Dict[str, Any], platform: Dict[str, Any]) -> GatewayType:
    org_type = org.get("gateway_type")
    if org_type in ("bifrost", "litellm_proxy"):
        return org_type
    platform_type = platform.get("gateway_type", "bifrost")
    if platform_type in ("bifrost", "litellm_proxy"):
        return platform_type
    return "bifrost"


def resolve_llm_gateway(
    organization_id: UUID,
    db: Session,
) -> Optional[LLMGatewayConfig]:
    """Return effective LLM gateway config, or ``None`` for direct routing."""
    platform = _platform_config()
    org = _get_org_raw_settings(organization_id, db)

    org_enabled = org.get("enabled")
    if org_enabled is False:
        return None

    if org_enabled is True:
        use_gateway = True
    elif platform["enabled"]:
        use_gateway = True
    else:
        return None

    if not use_gateway:
        return None

    gateway_type = _resolve_gateway_type(org, platform)

    base_url = (org.get("base_url") or platform["base_url"] or "").strip()
    if not base_url:
        logger.warning(
            "LLM gateway ({}) enabled for org {} but no base_url is configured; "
            "falling back to direct provider routing.",
            gateway_type,
            organization_id,
        )
        return None

    try:
        api_base = _normalize_base_url(base_url, gateway_type)
    except ValueError as exc:
        logger.warning(
            "Invalid LLM gateway base_url for org {} ({}): {}; falling back to direct routing.",
            organization_id,
            gateway_type,
            exc,
        )
        return None

    virtual_key = _decrypt_org_virtual_key(org) or platform["virtual_key"]
    master_key = _decrypt_org_master_key(org) or platform["master_key"]

    return LLMGatewayConfig(
        gateway_type=gateway_type,
        api_base=api_base,
        virtual_key=virtual_key,
        master_key=master_key,
        passthrough_provider_keys=platform["passthrough_provider_keys"],
    )


# Providers whose LiteLLM handlers build native API paths (e.g. Gemini
# ``:generateContent``) when ``api_base`` is set. Gateways like Bifrost and
# LiteLLM Proxy expect OpenAI-compatible ``/v1/chat/completions`` instead.
_NATIVE_GATEWAY_MODEL_PREFIXES = (
    "gemini/",
    "google/",
    "vertex/",
    "vertex_ai/",
)


def _model_uses_native_provider_path(model: Any) -> bool:
    model_str = str(model or "").lower()
    return any(model_str.startswith(prefix) for prefix in _NATIVE_GATEWAY_MODEL_PREFIXES)


def _apply_proxy_compatible_routing(call_kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Route native-path providers through the gateway's chat-completions API."""
    result = dict(call_kwargs)
    if _model_uses_native_provider_path(result.get("model")):
        result["custom_llm_provider"] = "openai"
    return result


def _strip_provider_keys(result: Dict[str, Any]) -> None:
    stored_key = result.get("api_key")
    if stored_key == GATEWAY_MANAGED_KEY_SENTINEL:
        result.pop("api_key", None)
    elif stored_key is not None:
        result.pop("api_key", None)


def _apply_bifrost_gateway(call_kwargs: Dict[str, Any], config: LLMGatewayConfig) -> Dict[str, Any]:
    result = dict(call_kwargs)
    result["api_base"] = config.api_base

    if config.virtual_key:
        extra_headers = dict(result.get("extra_headers") or {})
        extra_headers["x-bf-vk"] = config.virtual_key
        result["extra_headers"] = extra_headers

    if not config.passthrough_provider_keys:
        _strip_provider_keys(result)

    if not result.get("api_key"):
        result["api_key"] = config.virtual_key or LITELLM_GATEWAY_PLACEHOLDER_API_KEY

    model = result.get("model", "")
    if model and "/" not in str(model):
        logger.warning(
            "Routing model '{}' through Bifrost without a provider prefix; "
            "ensure the model is supported by both LiteLLM and Bifrost.",
            model,
        )

    return _apply_proxy_compatible_routing(result)


def _apply_litellm_proxy_gateway(call_kwargs: Dict[str, Any], config: LLMGatewayConfig) -> Dict[str, Any]:
    result = dict(call_kwargs)
    result["api_base"] = config.api_base

    if not config.passthrough_provider_keys:
        _strip_provider_keys(result)

    if not result.get("api_key"):
        result["api_key"] = config.master_key or LITELLM_GATEWAY_PLACEHOLDER_API_KEY

    return _apply_proxy_compatible_routing(result)


def apply_llm_gateway(
    call_kwargs: Dict[str, Any],
    *,
    organization_id: UUID,
    db: Session,
) -> Dict[str, Any]:
    """Merge gateway proxy settings into LiteLLM ``completion`` kwargs."""
    config = resolve_llm_gateway(organization_id, db)
    if config is None:
        return call_kwargs

    if config.gateway_type == "bifrost":
        return _apply_bifrost_gateway(call_kwargs, config)
    return _apply_litellm_proxy_gateway(call_kwargs, config)


def litellm_completion(
    *,
    organization_id: UUID,
    db: Session,
    **kwargs: Any,
):
    """Call ``litellm.completion`` with LLM gateway settings applied."""
    import litellm

    kwargs = apply_llm_gateway(kwargs, organization_id=organization_id, db=db)
    return litellm.completion(**kwargs)
