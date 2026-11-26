"""Client configuration: explicit arguments win, then environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from efficientai_sdk._exceptions import ConfigurationError

ENV_API_KEY = "EFFICIENTAI_API_KEY"
ENV_WORKSPACE_ID = "EFFICIENTAI_WORKSPACE_ID"
ENV_BASE_URL = "EFFICIENTAI_BASE_URL"
ENV_API_PREFIX = "EFFICIENTAI_API_PREFIX"
# Older name used by the in-framework trace helpers; still honoured.
ENV_BASE_URL_LEGACY = "EFFICIENTAI_API_BASE"

# EfficientAI is self-hosted; point EFFICIENTAI_BASE_URL at your deployment.
DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_API_PREFIX = "/api/v1"
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 2


def _env(name: str) -> Optional[str]:
    value = os.environ.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def normalize_api_prefix(prefix: str) -> str:
    cleaned = prefix.strip()
    if not cleaned.startswith("/"):
        cleaned = f"/{cleaned}"
    return cleaned.rstrip("/") or DEFAULT_API_PREFIX


def normalize_base_url(url: str, *, api_prefix: str = DEFAULT_API_PREFIX) -> str:
    """Strip trailing slashes and a trailing API prefix so paths can be appended."""
    cleaned = url.strip().rstrip("/")
    norm_prefix = normalize_api_prefix(api_prefix)
    for suffix in (norm_prefix, DEFAULT_API_PREFIX):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)].rstrip("/")
    if not cleaned.startswith(("http://", "https://")):
        raise ConfigurationError(f"base_url must start with http:// or https:// (got {url!r})")
    return cleaned


@dataclass(frozen=True)
class ClientConfig:
    api_key: str
    base_url: str
    api_prefix: str
    workspace_id: Optional[str]
    timeout: float
    max_retries: int

    def api_path(self, suffix: str) -> str:
        return f"{self.api_prefix}/{suffix.lstrip('/')}"

    def __repr__(self) -> str:  # never print the key
        return (
            f"ClientConfig(base_url={self.base_url!r}, api_prefix={self.api_prefix!r}, "
            f"workspace_id={self.workspace_id!r}, "
            f"timeout={self.timeout!r}, max_retries={self.max_retries!r}, api_key='***')"
        )


def resolve_config(
    *,
    api_key: Optional[str] = None,
    workspace_id: Optional[str] = None,
    base_url: Optional[str] = None,
    api_prefix: Optional[str] = None,
    timeout: Optional[float] = None,
    max_retries: Optional[int] = None,
) -> ClientConfig:
    key = (api_key or "").strip() or _env(ENV_API_KEY)
    if not key:
        raise ConfigurationError(
            f"No API key provided. Pass api_key=... or set the {ENV_API_KEY} environment variable."
        )

    url = (base_url or "").strip() or _env(ENV_BASE_URL) or _env(ENV_BASE_URL_LEGACY)
    prefix = (api_prefix or "").strip() or _env(ENV_API_PREFIX) or DEFAULT_API_PREFIX
    norm_prefix = normalize_api_prefix(prefix)
    workspace = (str(workspace_id).strip() if workspace_id else None) or _env(ENV_WORKSPACE_ID)

    resolved_timeout = DEFAULT_TIMEOUT if timeout is None else float(timeout)
    if resolved_timeout <= 0:
        raise ConfigurationError("timeout must be greater than 0")
    resolved_retries = DEFAULT_MAX_RETRIES if max_retries is None else int(max_retries)
    if resolved_retries < 0:
        raise ConfigurationError("max_retries must be 0 or greater")

    return ClientConfig(
        api_key=key,
        base_url=normalize_base_url(url or DEFAULT_BASE_URL, api_prefix=norm_prefix),
        api_prefix=norm_prefix,
        workspace_id=workspace,
        timeout=resolved_timeout,
        max_retries=resolved_retries,
    )
