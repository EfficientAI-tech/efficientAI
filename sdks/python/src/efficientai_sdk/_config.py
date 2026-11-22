"""Client configuration: explicit arguments win, then environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from efficientai_sdk._exceptions import ConfigurationError

ENV_API_KEY = "EFFICIENTAI_API_KEY"
ENV_WORKSPACE_ID = "EFFICIENTAI_WORKSPACE_ID"
ENV_BASE_URL = "EFFICIENTAI_BASE_URL"
# Older name used by the in-framework trace helpers; still honoured.
ENV_BASE_URL_LEGACY = "EFFICIENTAI_API_BASE"

# EfficientAI is self-hosted; point EFFICIENTAI_BASE_URL at your deployment.
DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 2

_API_PREFIX = "/api/v1"


def _env(name: str) -> Optional[str]:
    value = os.environ.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def normalize_base_url(url: str) -> str:
    """Strip trailing slashes and a trailing ``/api/v1`` so paths can be appended."""
    cleaned = url.strip().rstrip("/")
    if cleaned.endswith(_API_PREFIX):
        cleaned = cleaned[: -len(_API_PREFIX)].rstrip("/")
    if not cleaned.startswith(("http://", "https://")):
        raise ConfigurationError(f"base_url must start with http:// or https:// (got {url!r})")
    return cleaned


@dataclass(frozen=True)
class ClientConfig:
    api_key: str
    base_url: str
    workspace_id: Optional[str]
    timeout: float
    max_retries: int

    def __repr__(self) -> str:  # never print the key
        return (
            f"ClientConfig(base_url={self.base_url!r}, workspace_id={self.workspace_id!r}, "
            f"timeout={self.timeout!r}, max_retries={self.max_retries!r}, api_key='***')"
        )


def resolve_config(
    *,
    api_key: Optional[str] = None,
    workspace_id: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout: Optional[float] = None,
    max_retries: Optional[int] = None,
) -> ClientConfig:
    key = (api_key or "").strip() or _env(ENV_API_KEY)
    if not key:
        raise ConfigurationError(
            f"No API key provided. Pass api_key=... or set the {ENV_API_KEY} environment variable."
        )

    url = (base_url or "").strip() or _env(ENV_BASE_URL) or _env(ENV_BASE_URL_LEGACY)
    workspace = (str(workspace_id).strip() if workspace_id else None) or _env(ENV_WORKSPACE_ID)

    resolved_timeout = DEFAULT_TIMEOUT if timeout is None else float(timeout)
    if resolved_timeout <= 0:
        raise ConfigurationError("timeout must be greater than 0")
    resolved_retries = DEFAULT_MAX_RETRIES if max_retries is None else int(max_retries)
    if resolved_retries < 0:
        raise ConfigurationError("max_retries must be 0 or greater")

    return ClientConfig(
        api_key=key,
        base_url=normalize_base_url(url or DEFAULT_BASE_URL),
        workspace_id=workspace,
        timeout=resolved_timeout,
        max_retries=resolved_retries,
    )
