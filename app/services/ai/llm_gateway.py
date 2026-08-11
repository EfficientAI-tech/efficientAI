"""
LLM gateway resolver for batch/eval LiteLLM workloads.

Supports Bifrost (/litellm proxy) and self-hosted LiteLLM Proxy gateways.
Platform defaults live in ``config.yml``; per-org overrides are stored in
``organizations.llm_gateway_settings`` JSON. Per-credential overrides live on
``aiproviders`` and ``integrations`` rows.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional, Tuple
from urllib.parse import urlparse
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.config import settings


GatewayType = Literal["bifrost", "litellm_proxy"]
GatewayInterface = Literal["litellm_shim", "native_openai"]
GatewayInterfaceOverride = Literal["inherit", "litellm_shim", "native_openai"]
RoutingMode = Literal["inherit", "gateway", "direct"]
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


@dataclass(frozen=True)
class CredentialRoutingContext:
    """Per-credential routing preferences."""

    routing_mode: RoutingMode = "inherit"
    gateway_model: Optional[str] = None
    gateway_interface: GatewayInterfaceOverride = "inherit"
    gateway_base_url: Optional[str] = None
    gateway_auth_header: Optional[str] = None
    gateway_auth_secret_env: Optional[str] = None
    gateway_auth_secret: Optional[str] = None
    gateway_extra_headers: Optional[Dict[str, str]] = None


def _normalize_routing_mode(value: Any) -> RoutingMode:
    mode = value.value if hasattr(value, "value") else value
    mode = str(mode or "inherit").strip().lower()
    if mode in ("inherit", "gateway", "direct"):
        return mode  # type: ignore[return-value]
    return "inherit"


def _normalize_gateway_interface(value: Any) -> GatewayInterfaceOverride:
    iface = value.value if hasattr(value, "value") else value
    iface = str(iface or "inherit").strip().lower()
    if iface in ("inherit", "litellm_shim", "native_openai"):
        return iface  # type: ignore[return-value]
    return "inherit"


def _normalize_gateway_extra_headers(value: Any) -> Optional[Dict[str, str]]:
    if not value:
        return None
    if not isinstance(value, dict):
        return None
    normalized: Dict[str, str] = {}
    for raw_key, raw_val in value.items():
        key = str(raw_key).strip()
        if not key:
            continue
        normalized[key] = str(raw_val)
    return normalized or None


def _decrypt_gateway_auth_secret(encrypted: Any) -> Optional[str]:
    if not encrypted:
        return None
    try:
        from app.core.encryption import decrypt_api_key

        return decrypt_api_key(encrypted)
    except Exception as exc:
        logger.warning("Failed to decrypt credential gateway auth secret: {}", exc)
        return None


def routing_context_from_ai_provider(provider: Any) -> CredentialRoutingContext:
    """Build routing context from an ``AIProvider`` row."""
    gateway_model = getattr(provider, "gateway_model", None)
    if gateway_model:
        gateway_model = str(gateway_model).strip() or None
    gateway_base_url = getattr(provider, "gateway_base_url", None)
    if gateway_base_url:
        gateway_base_url = str(gateway_base_url).strip() or None
    gateway_auth_header = getattr(provider, "gateway_auth_header", None)
    if gateway_auth_header:
        gateway_auth_header = str(gateway_auth_header).strip() or None
    gateway_auth_secret_env = getattr(provider, "gateway_auth_secret_env", None)
    if gateway_auth_secret_env:
        gateway_auth_secret_env = str(gateway_auth_secret_env).strip() or None
    return CredentialRoutingContext(
        routing_mode=_normalize_routing_mode(getattr(provider, "routing_mode", "inherit")),
        gateway_model=gateway_model,
        gateway_interface=_normalize_gateway_interface(
            getattr(provider, "gateway_interface", "inherit")
        ),
        gateway_base_url=gateway_base_url,
        gateway_auth_header=gateway_auth_header,
        gateway_auth_secret_env=gateway_auth_secret_env,
        gateway_auth_secret=_decrypt_gateway_auth_secret(
            getattr(provider, "gateway_auth_secret", None)
        ),
        gateway_extra_headers=_normalize_gateway_extra_headers(
            getattr(provider, "gateway_extra_headers", None)
        ),
    )


def routing_context_from_integration(integration: Any) -> CredentialRoutingContext:
    """Build routing context from a voice-platform ``Integration`` row."""
    return CredentialRoutingContext(
        routing_mode=_normalize_routing_mode(getattr(integration, "routing_mode", "inherit")),
    )


def resolve_litellm_model(
    *,
    workload_model_str: str,
    gateway_active: bool,
    credential: Optional[CredentialRoutingContext],
) -> str:
    """Pick a Bifrost custom model or use the workload-built model string."""
    if gateway_active and credential and credential.gateway_model:
        return credential.gateway_model
    return workload_model_str


def resolve_litellm_api_key(
    organization_id: UUID,
    db: Session,
    ai_provider: Any,
    *,
    credential: Optional[CredentialRoutingContext] = None,
) -> Optional[str]:
    """Decrypt the org credential, or return None when the gateway supplies the key."""
    from app.core.encryption import decrypt_api_key

    ctx = credential or routing_context_from_ai_provider(ai_provider)

    try:
        raw_key = decrypt_api_key(ai_provider.api_key)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to decrypt API key for provider {ai_provider.provider}: {exc}"
        ) from exc

    gateway_config, effective = resolve_effective_routing(organization_id, db, ctx)

    if effective == "direct":
        if raw_key == GATEWAY_MANAGED_KEY_SENTINEL:
            raise RuntimeError(
                "AI provider is configured for gateway-managed credentials, "
                "but routing is set to direct. Add a provider API key or "
                "change routing mode to gateway."
            )
        return raw_key

    if raw_key == GATEWAY_MANAGED_KEY_SENTINEL:
        return None

    return raw_key


@dataclass(frozen=True)
class LLMGatewayConfig:
    """Resolved gateway settings for a single LiteLLM call."""

    gateway_type: GatewayType
    gateway_interface: GatewayInterface
    api_base: str
    virtual_key: Optional[str] = None
    auth_header: str = "x-bf-vk"
    extra_headers: Optional[Dict[str, str]] = None
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


_NATIVE_OPENAI_PATH_SUFFIXES = (
    "/v1/chat/completions",
    "/v1/completions",
    "/chat/completions",
    "/litellm",
)


def normalize_bifrost_native_url(base_url: str) -> str:
    """Ensure a Bifrost native OpenAI-compatible URL is well-formed.

    LiteLLM passes ``api_base`` to the OpenAI client, which appends
    ``/chat/completions`` (not ``/v1/chat/completions``). The base must
    therefore end with ``/v1``, e.g. ``http://localhost:8080/v1``.
    """
    url = (base_url or "").strip().rstrip("/")
    if not url:
        return ""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(
            "Bifrost base_url must be an absolute URL including scheme and host "
            "(e.g. http://localhost:8080)."
        )
    original = url
    stripped_paths = False
    while True:
        stripped = False
        for suffix in _NATIVE_OPENAI_PATH_SUFFIXES:
            if url.endswith(suffix):
                url = url[: -len(suffix)]
                stripped = True
                stripped_paths = True
                break
        if not stripped:
            break
    if not url.endswith("/v1"):
        url = f"{url}/v1"
    if stripped_paths:
        logger.warning(
            "Normalized native Bifrost base_url '{}' -> '{}'. "
            "Use the host root only (e.g. http://localhost:8080); "
            "/v1 is appended automatically for LiteLLM.",
            original,
            url,
        )
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


def _normalize_base_url(
    base_url: str,
    gateway_type: GatewayType,
    gateway_interface: GatewayInterface,
) -> str:
    if gateway_type == "bifrost":
        if gateway_interface == "native_openai":
            return normalize_bifrost_native_url(base_url)
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
        "gateway_interface": (settings.LLM_GATEWAY_INTERFACE or "litellm_shim").strip().lower(),
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


def _resolve_gateway_interface(
    credential: Optional[CredentialRoutingContext],
    org: Dict[str, Any],
    platform: Dict[str, Any],
) -> GatewayInterface:
    if credential and credential.gateway_interface in ("litellm_shim", "native_openai"):
        return credential.gateway_interface

    org_interface = org.get("gateway_interface")
    if org_interface in ("litellm_shim", "native_openai"):
        return org_interface

    platform_interface = platform.get("gateway_interface", "litellm_shim")
    if platform_interface in ("litellm_shim", "native_openai"):
        return platform_interface

    return "litellm_shim"


def _resolve_gateway_base_url(
    credential: Optional[CredentialRoutingContext],
    org: Dict[str, Any],
    platform: Dict[str, Any],
) -> str:
    if credential and credential.gateway_base_url:
        return credential.gateway_base_url.strip()
    return (org.get("base_url") or platform.get("base_url") or "").strip()


def _resolve_gateway_auth_header(credential: Optional[CredentialRoutingContext]) -> str:
    if credential and credential.gateway_auth_header:
        header = credential.gateway_auth_header.strip()
        if header:
            return header
    return "x-bf-vk"


def _resolve_gateway_auth_secret(
    credential: Optional[CredentialRoutingContext],
    org: Dict[str, Any],
    platform: Dict[str, Any],
) -> Optional[str]:
    if credential and credential.gateway_auth_secret_env:
        env_name = credential.gateway_auth_secret_env.strip()
        if env_name:
            secret = (os.environ.get(env_name) or "").strip()
            if secret:
                return secret
            logger.warning(
                "Gateway auth env var '{}' is unset or empty; falling back to org/platform keys.",
                env_name,
            )

    if credential and credential.gateway_auth_secret:
        return credential.gateway_auth_secret.strip() or None

    return _decrypt_org_virtual_key(org) or platform.get("virtual_key")


def _format_gateway_auth_header_value(header_name: str, secret: str) -> str:
    if header_name.lower() == "authorization":
        if secret.lower().startswith("bearer "):
            return secret
        return f"Bearer {secret}"
    return secret


def _org_wants_gateway(
    org: Dict[str, Any],
    platform: Dict[str, Any],
    *,
    credential_mode: RoutingMode,
) -> bool:
    """Return whether org/platform settings want gateway routing for inherit mode."""
    if credential_mode == "gateway":
        return True
    if credential_mode == "direct":
        return False

    org_enabled = org.get("enabled")
    if org_enabled is False:
        return False
    if org_enabled is True:
        return True
    return bool(platform["enabled"])


def _build_gateway_config(
    organization_id: UUID,
    org: Dict[str, Any],
    platform: Dict[str, Any],
    *,
    credential: Optional[CredentialRoutingContext],
    credential_mode: RoutingMode,
    strict: bool,
) -> Optional[LLMGatewayConfig]:
    """Resolve gateway connection details from org/platform/credential settings."""
    gateway_type = _resolve_gateway_type(org, platform)
    gateway_interface = _resolve_gateway_interface(credential, org, platform)
    base_url = _resolve_gateway_base_url(credential, org, platform)

    if not base_url:
        message = (
            f"LLM gateway ({gateway_type}) is required for credential routing "
            f"mode '{credential_mode}' but no base_url is configured for org "
            f"{organization_id}."
        )
        if strict:
            raise RuntimeError(message)
        logger.warning("{} Falling back to direct provider routing.", message)
        return None

    try:
        api_base = _normalize_base_url(base_url, gateway_type, gateway_interface)
    except ValueError as exc:
        message = (
            f"Invalid LLM gateway base_url for org {organization_id} "
            f"({gateway_type}): {exc}"
        )
        if strict:
            raise RuntimeError(message) from exc
        logger.warning("{} Falling back to direct provider routing.", message)
        return None

    virtual_key = _resolve_gateway_auth_secret(credential, org, platform)
    auth_header = _resolve_gateway_auth_header(credential)
    extra_headers = (
        dict(credential.gateway_extra_headers)
        if credential and credential.gateway_extra_headers
        else None
    )
    master_key = _decrypt_org_master_key(org) or platform["master_key"]

    return LLMGatewayConfig(
        gateway_type=gateway_type,
        gateway_interface=gateway_interface if gateway_type == "bifrost" else "litellm_shim",
        api_base=api_base,
        virtual_key=virtual_key,
        auth_header=auth_header,
        extra_headers=extra_headers,
        master_key=master_key,
        passthrough_provider_keys=platform["passthrough_provider_keys"],
    )


def resolve_effective_routing(
    organization_id: UUID,
    db: Session,
    credential: Optional[CredentialRoutingContext] = None,
) -> Tuple[Optional[LLMGatewayConfig], EffectiveRouting]:
    """Merge org/platform gateway config with per-credential override."""
    platform = _platform_config()
    org = _get_org_raw_settings(organization_id, db)
    credential_mode = credential.routing_mode if credential else "inherit"

    if credential_mode == "direct":
        return None, "direct"

    use_gateway = _org_wants_gateway(org, platform, credential_mode=credential_mode)
    if not use_gateway:
        return None, "direct"

    strict = credential_mode == "gateway"
    config = _build_gateway_config(
        organization_id,
        org,
        platform,
        credential=credential,
        credential_mode=credential_mode,
        strict=strict,
    )
    if config is None:
        return None, "direct"

    return config, config.gateway_type


def resolve_llm_gateway(
    organization_id: UUID,
    db: Session,
    *,
    credential: Optional[CredentialRoutingContext] = None,
) -> Optional[LLMGatewayConfig]:
    """Return effective LLM gateway config, or ``None`` for direct routing."""
    config, effective = resolve_effective_routing(organization_id, db, credential)
    if effective == "direct":
        return None
    return config


def get_credential_effective_gateway_interface(
    organization_id: UUID,
    db: Session,
    gateway_interface: Optional[str],
) -> GatewayInterface:
    """Resolved Bifrost API surface for a credential (for API responses)."""
    credential = CredentialRoutingContext(
        gateway_interface=_normalize_gateway_interface(gateway_interface or "inherit"),
    )
    org = _get_org_raw_settings(organization_id, db)
    platform = _platform_config()
    return _resolve_gateway_interface(credential, org, platform)


def get_credential_effective_routing_label(
    organization_id: UUID,
    db: Session,
    routing_mode: Any,
) -> EffectiveRouting:
    """Resolved routing label for API responses."""
    ctx = CredentialRoutingContext(routing_mode=_normalize_routing_mode(routing_mode))
    _, effective = resolve_effective_routing(organization_id, db, ctx)
    return effective


# Gateways speak OpenAI-compatible ``/v1/chat/completions``. LiteLLM
# otherwise auto-detects bare names like ``gemini-2.5-flash`` as Vertex
# native and bypasses ``api_base``.


def _apply_proxy_compatible_routing(
    call_kwargs: Dict[str, Any],
    *,
    routing_model: Optional[str] = None,
) -> Dict[str, Any]:
    """Force OpenAI chat-completions routing when the model needs proxy translation."""
    result = dict(call_kwargs)
    model = routing_model or result.get("model")

    if model and str(model).startswith("azure/"):
        result["custom_llm_provider"] = "openai"
        result["model"] = "openai/gpt-4o-mini"
        return result

    if model and str(model).startswith("openai/"):
        return result

    result["custom_llm_provider"] = "openai"
    return result


def _strip_provider_keys(result: Dict[str, Any]) -> None:
    stored_key = result.get("api_key")
    if stored_key == GATEWAY_MANAGED_KEY_SENTINEL:
        result.pop("api_key", None)
    elif stored_key is not None:
        result.pop("api_key", None)


def _merge_gateway_extra_headers(
    call_kwargs: Dict[str, Any],
    config: LLMGatewayConfig,
) -> Dict[str, str]:
    merged = dict(call_kwargs.get("extra_headers") or {})
    if config.extra_headers:
        merged.update(config.extra_headers)
    if config.virtual_key:
        header_name = config.auth_header or "x-bf-vk"
        merged[header_name] = _format_gateway_auth_header_value(
            header_name,
            config.virtual_key,
        )
    return merged


def _apply_bifrost_gateway(
    call_kwargs: Dict[str, Any],
    config: LLMGatewayConfig,
    *,
    routing_model: Optional[str] = None,
) -> Dict[str, Any]:
    result = dict(call_kwargs)
    result["api_base"] = config.api_base

    merged_headers = _merge_gateway_extra_headers(result, config)
    if merged_headers:
        result["extra_headers"] = merged_headers

    if not config.passthrough_provider_keys:
        _strip_provider_keys(result)

    if not result.get("api_key"):
        result["api_key"] = config.virtual_key or LITELLM_GATEWAY_PLACEHOLDER_API_KEY

    return _apply_proxy_compatible_routing(result, routing_model=routing_model)


def _apply_litellm_proxy_gateway(
    call_kwargs: Dict[str, Any],
    config: LLMGatewayConfig,
    *,
    routing_model: Optional[str] = None,
) -> Dict[str, Any]:
    result = dict(call_kwargs)
    result["api_base"] = config.api_base

    merged_headers = _merge_gateway_extra_headers(result, config)
    if merged_headers:
        result["extra_headers"] = merged_headers

    if not config.passthrough_provider_keys:
        _strip_provider_keys(result)

    if not result.get("api_key"):
        result["api_key"] = config.master_key or LITELLM_GATEWAY_PLACEHOLDER_API_KEY

    return _apply_proxy_compatible_routing(result, routing_model=routing_model)


def apply_llm_gateway(
    call_kwargs: Dict[str, Any],
    *,
    organization_id: UUID,
    db: Session,
    model: Optional[str] = None,
    credential: Optional[CredentialRoutingContext] = None,
) -> Dict[str, Any]:
    """Merge gateway proxy settings into LiteLLM ``completion`` kwargs.

    Pass ``model`` when the caller supplies the model separately (e.g. GEPA
    ``DefaultAdapter``) so native-path routing still applies without putting
    ``model`` in the returned kwargs.
    """
    config = resolve_llm_gateway(organization_id, db, credential=credential)
    if config is None:
        return call_kwargs

    if config.gateway_type == "bifrost":
        return _apply_bifrost_gateway(call_kwargs, config, routing_model=model)
    return _apply_litellm_proxy_gateway(call_kwargs, config, routing_model=model)


def litellm_completion(
    *,
    organization_id: UUID,
    db: Session,
    credential: Optional[CredentialRoutingContext] = None,
    **kwargs: Any,
):
    """Call ``litellm.completion`` with LLM gateway settings applied."""
    import litellm

    kwargs = apply_llm_gateway(
        kwargs,
        organization_id=organization_id,
        db=db,
        credential=credential,
    )
    response = litellm.completion(**kwargs)
    try:
        from app.services.usage.context import (
            LLMUsageProductSection,
            ensure_usage_context,
            reset_usage_context,
        )
        from app.services.usage.llm_usage import record_llm_usage
        from app.services.usage.normalize import normalize_llm_usage

        usage_token = ensure_usage_context(
            organization_id,
            product_section=LLMUsageProductSection.OTHER,
        )
        try:
            model_name = str(kwargs.get("model") or "unknown")
            if "/" in model_name:
                model_name = model_name.rsplit("/", 1)[-1]
            record_llm_usage(model_name, normalize_llm_usage(raw_response=response))
        finally:
            if usage_token is not None:
                reset_usage_context(usage_token)
    except Exception as exc:
        logger.debug("litellm_completion usage record skipped: {}", exc)
    return response
