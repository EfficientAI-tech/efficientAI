"""URL helpers for routing live voice WebSockets to the media server."""

from __future__ import annotations

from typing import Optional
from urllib.parse import quote, urlparse

from starlette.requests import Request

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


def resolve_voice_agent_ws_base(
    *,
    fallback_host: Optional[str] = None,
    fallback_scheme: str = "http",
) -> str:
    """Resolve the WebSocket origin used for browser voice-agent connections."""
    ws_base = media_ws_base_url()
    if ws_base:
        return ws_base
    if (settings.PUBLIC_BASE_URL or "").strip():
        public = settings.PUBLIC_BASE_URL.strip().rstrip("/")
        if public.startswith("https://"):
            return "wss://" + public[len("https://") :]
        if public.startswith("http://"):
            return "ws://" + public[len("http://") :]
        if public.startswith("wss://") or public.startswith("ws://"):
            return public
        return f"wss://{public}"
    if fallback_host:
        return ws_base_from_http_host(fallback_host, scheme=fallback_scheme)
    return f"ws://localhost:{settings.PORT}"


def cross_host_voice_ws(ws_base: str, request: Request) -> bool:
    """True when the WS host cannot receive the API's host-scoped session cookies."""
    ws_hostname = (urlparse(ws_base).hostname or "").lower()
    req_hostname = (request.url.hostname or "").lower()
    if not ws_hostname or not req_hostname:
        return False
    return ws_hostname != req_hostname


def build_voice_agent_ws_url(
    *,
    auth_query: Optional[str] = None,
    agent_id: Optional[str] = None,
    persona_id: Optional[str] = None,
    scenario_id: Optional[str] = None,
    run_evaluation: bool = False,
    ui_surface: Optional[str] = None,
    fallback_host: Optional[str] = None,
    fallback_scheme: str = "http",
) -> str:
    """Build the browser voice-agent WebSocket URL."""
    base = resolve_voice_agent_ws_base(
        fallback_host=fallback_host,
        fallback_scheme=fallback_scheme,
    )

    query_parts: list[str] = []
    if auth_query:
        query_parts.append(auth_query)
    if agent_id:
        query_parts.append(f"agent_id={quote(agent_id)}")
    if persona_id:
        query_parts.append(f"persona_id={quote(persona_id)}")
    if scenario_id:
        query_parts.append(f"scenario_id={quote(scenario_id)}")
    if run_evaluation:
        query_parts.append("run_evaluation=true")
    if ui_surface:
        query_parts.append(f"ui_surface={quote(ui_surface, safe='')}")

    path = f"{base}{settings.API_V1_PREFIX}/voice-agent/ws"
    if not query_parts:
        return path
    return f"{path}?{'&'.join(query_parts)}"
