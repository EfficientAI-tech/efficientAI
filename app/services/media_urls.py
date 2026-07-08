"""URL helpers for routing live voice WebSockets to the media server."""

from __future__ import annotations

from typing import Optional
from urllib.parse import quote

from app.config import settings


def media_ws_base_url() -> Optional[str]:
    """Return configured media WebSocket base (wss://host[:port]) or None."""
    base = (settings.MEDIA_WS_BASE_URL or "").strip()
    if not base:
        webhook_base = (settings.VOBIZ_WEBHOOK_BASE_URL or settings.PLIVO_WEBHOOK_BASE_URL or "").strip()
        if not webhook_base:
            return None
        base = webhook_base
    base = base.rstrip("/")
    if base.startswith("https://"):
        return "wss://" + base[len("https://") :]
    if base.startswith("http://"):
        return "ws://" + base[len("http://") :]
    if base.startswith("wss://") or base.startswith("ws://"):
        return base
    return f"wss://{base}"


def build_voice_agent_ws_url(
    *,
    auth_query: str,
    agent_id: Optional[str] = None,
    persona_id: Optional[str] = None,
    scenario_id: Optional[str] = None,
    fallback_host: Optional[str] = None,
) -> str:
    """Build the browser voice-agent WebSocket URL."""
    ws_base = media_ws_base_url()
    if ws_base:
        base = ws_base
    elif fallback_host:
        base = f"ws://{fallback_host}"
    else:
        base = f"ws://localhost:{settings.PORT}"

    query = auth_query
    if agent_id:
        query += f"&agent_id={quote(agent_id)}"
    if persona_id:
        query += f"&persona_id={quote(persona_id)}"
    if scenario_id:
        query += f"&scenario_id={quote(scenario_id)}"

    return f"{base}{settings.API_V1_PREFIX}/voice-agent/ws?{query}"
