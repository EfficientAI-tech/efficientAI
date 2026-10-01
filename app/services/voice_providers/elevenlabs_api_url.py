"""Normalize ElevenLabs API base URLs for integrations and providers."""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse

ELEVENLABS_GLOBAL_ORIGIN = "https://api.elevenlabs.io"


def _is_allowed_elevenlabs_host(hostname: str) -> bool:
    host = (hostname or "").lower().strip(".")
    if not host:
        return False
    if host == "api.elevenlabs.io":
        return True
    return host.endswith(".elevenlabs.io")


def normalize_elevenlabs_api_base_url(raw: Optional[str]) -> Optional[str]:
    """
    Normalize user input to an origin (scheme + host, no path) for storage.

    Returns None when blank or equal to the global default.
    """
    if raw is None:
        return None
    trimmed = raw.strip()
    if not trimmed:
        return None

    parsed = urlparse(trimmed if "://" in trimmed else f"https://{trimmed}")
    if parsed.scheme.lower() != "https":
        raise ValueError("ElevenLabs API base URL must use https://")

    hostname = (parsed.hostname or "").lower()
    if not _is_allowed_elevenlabs_host(hostname):
        raise ValueError(
            "ElevenLabs API base URL must be api.elevenlabs.io or a *.elevenlabs.io residency host"
        )

    path = (parsed.path or "").rstrip("/")
    if path and path not in ("/v1", ""):
        raise ValueError(
            "ElevenLabs API base URL must be the host only (optional /v1 suffix), not a deeper path"
        )

    origin = f"https://{hostname}"
    if origin == ELEVENLABS_GLOBAL_ORIGIN:
        return None
    return origin


def elevenlabs_http_origin(stored_origin: Optional[str]) -> str:
    """HTTPS origin for ElevenLabs HTTP APIs (TTS/STT), without /v1."""
    return (stored_origin or "").strip() or ELEVENLABS_GLOBAL_ORIGIN


def elevenlabs_api_v1_base(stored_origin: Optional[str]) -> str:
    """Build the /v1 base used by ElevenLabsVoiceProvider."""
    return f"{elevenlabs_http_origin(stored_origin).rstrip('/')}/v1"


def elevenlabs_speech_to_text_url(stored_origin: Optional[str] = None) -> str:
    return f"{elevenlabs_api_v1_base(stored_origin)}/speech-to-text"


def elevenlabs_realtime_stt_host(stored_origin: Optional[str]) -> str:
    """Hostname for ElevenLabs Realtime STT WebSocket (no scheme)."""
    host = urlparse(elevenlabs_http_origin(stored_origin)).hostname
    return host or "api.elevenlabs.io"
