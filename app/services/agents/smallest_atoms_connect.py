"""Smallest Atoms text chat WebSocket URL (official mode=chat contract)."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from loguru import logger

SMALLEST_ATOMS_WSS_BASE = "wss://api.smallest.ai/atoms/v1"


def chat_websocket_uri(
    api_key: str,
    agent_id: str,
    *,
    variables: dict[str, Any] | None = None,
) -> str:
    """Realtime text chat — token + agent_id query params (see smallest-inc/mcp-server chat-client)."""
    params = [
        f"token={quote(api_key.strip(), safe='')}",
        f"agent_id={quote(agent_id.strip(), safe='')}",
        "mode=chat",
    ]
    if variables:
        params.append(f"variables={quote(json.dumps(variables), safe='')}")
    return f"{SMALLEST_ATOMS_WSS_BASE}/agent/connect?{'&'.join(params)}"


def parse_inbound_event(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.debug("Smallest chat non-JSON frame: {!r}", raw[:200])
            return None
    else:
        parsed = raw
    if isinstance(parsed, dict):
        if parsed.get("type"):
            return parsed
        nested = parsed.get("event") or parsed.get("data") or parsed.get("payload")
        if isinstance(nested, dict) and nested.get("type"):
            return nested
        return parsed if parsed.get("type") else None
    return None
