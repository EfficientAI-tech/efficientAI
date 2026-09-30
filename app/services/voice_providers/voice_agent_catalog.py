"""List remote voice agents for integration picker UIs."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.models.database import Integration
from app.services.voice_providers.prompt_sync import _build_voice_provider

CACHE_TTL_SECONDS = 60
_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
_cache_lock = threading.Lock()


@dataclass
class VoiceAgentListResult:
    agents: List[Dict[str, str]]
    platform: str
    cached: bool
    truncated: bool
    list_supported: bool
    message: Optional[str] = None


def _cache_key(integration_id: str, search: Optional[str]) -> str:
    return f"{integration_id}:{(search or '').strip().lower()}"


def list_integration_voice_agents(
    integration: Integration,
    *,
    refresh: bool = False,
    search: Optional[str] = None,
) -> VoiceAgentListResult:
    platform_val = (
        integration.platform.value
        if hasattr(integration.platform, "value")
        else str(integration.platform)
    )
    key = _cache_key(str(integration.id), search)

    if not refresh:
        with _cache_lock:
            cached = _cache.get(key)
            if cached and (time.time() - cached[0]) < CACHE_TTL_SECONDS:
                return VoiceAgentListResult(**cached[1], cached=True)

    provider = _build_voice_provider(integration)
    truncated = False
    message: Optional[str] = None
    list_supported = True

    try:
        agents = provider.list_agents(search=search)
        if platform_val.lower() == "elevenlabs":
            truncated = bool(getattr(provider, "last_list_truncated", False))
            if truncated:
                message = "Showing the first 1,000 ElevenLabs agents. Use search to narrow results."
    except NotImplementedError:
        agents = []
        list_supported = False
        message = "This platform does not support listing agents. Enter the agent ID manually."
    except Exception as exc:
        raise ValueError(str(exc)) from exc

    payload = {
        "agents": agents,
        "platform": platform_val,
        "cached": False,
        "truncated": truncated,
        "list_supported": list_supported,
        "message": message,
    }

    with _cache_lock:
        _cache[key] = (time.time(), payload)

    return VoiceAgentListResult(**payload)
