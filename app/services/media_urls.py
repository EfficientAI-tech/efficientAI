"""URL helpers for routing live voice WebSockets to the media server."""

from __future__ import annotations

from typing import Optional
from urllib.parse import quote

from app.config import settings


def _normalize_ws_base(base: str) -> str:
    base = base.rstrip("/")
    if base.startswith("https://"):
        return "wss://" + base[len("https://") :]
    if base.startswith("http://"):
        return "ws://" + base[len("http://") :]
    if base.startswith("wss://") or base.startswith("ws://"):
        return base
    return f"wss://{base}"


def media_ws_base_url() -> Optional[str]:
    """Explicit dedicated media server base (``MEDIA_WS_BASE_URL`` / config only)."""
    base = (settings.MEDIA_WS_BASE_URL or "").strip()
    if not base:
        return None
    return _normalize_ws_base(base)


def carrier_media_ws_base_url() -> Optional[str]:
    """
    WebSocket base for carrier (Vobiz) answer XML.

    Uses ``MEDIA_WS_BASE_URL`` when set; otherwise reuses the telephony edge
    webhook base (``vobiz_webhook_base_url`` / config) so a single public host
    serves Vobiz webhooks and live audio.
    """
    explicit = media_ws_base_url()
    if explicit:
        return explicit
    try:
        from app.services.telephony.vobiz_agent_context import vobiz_webhook_base_url

        return _normalize_ws_base(vobiz_webhook_base_url())
    except ValueError:
        pass
    webhook_base = (settings.VOBIZ_WEBHOOK_BASE_URL or settings.PLIVO_WEBHOOK_BASE_URL or "").strip()
    if not webhook_base:
        return None
    return _normalize_ws_base(webhook_base)


def separate_media_server_configured() -> bool:
    """True when live voice WebSockets should run on a dedicated media process."""
    return bool((settings.MEDIA_WS_BASE_URL or "").strip())


def ws_base_from_http_host(host: str, *, scheme: str = "http") -> str:
    """Build ws/wss base from an HTTP Host header (browser / reverse-proxy)."""
    ws_scheme = "wss" if scheme == "https" else "ws"
    return f"{ws_scheme}://{host.rstrip('/')}"


def build_voice_agent_ws_url(
    *,
    auth_query: str,
    agent_id: Optional[str] = None,
    persona_id: Optional[str] = None,
    scenario_id: Optional[str] = None,
    ui_surface: Optional[str] = None,
    fallback_host: Optional[str] = None,
    fallback_scheme: str = "http",
) -> str:
    """Build the browser voice-agent WebSocket URL."""
    ws_base = media_ws_base_url()
    if ws_base:
        base = ws_base
    elif fallback_host:
        base = ws_base_from_http_host(fallback_host, scheme=fallback_scheme)
    else:
        base = f"ws://localhost:{settings.PORT}"

    query = auth_query
    if agent_id:
        query += f"&agent_id={quote(agent_id)}"
    if persona_id:
        query += f"&persona_id={quote(persona_id)}"
    if scenario_id:
        query += f"&scenario_id={quote(scenario_id)}"
    if ui_surface:
        query += f"&ui_surface={quote(ui_surface, safe='')}"

    return f"{base}{settings.API_V1_PREFIX}/voice-agent/ws?{query}"
