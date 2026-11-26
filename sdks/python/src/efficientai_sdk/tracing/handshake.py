"""Parse the trace handshake EfficientAI sends to an agent at the start of a test call."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional

__all__ = ["HANDSHAKE_TYPE", "LEGACY_CALL_SHORT_ID_KEY", "parse_trace_handshake"]

HANDSHAKE_TYPE = "efficientai_trace_handshake"
LEGACY_CALL_SHORT_ID_KEY = "efficientai_call_short_id"


def _normalized(message: Mapping[str, Any], call_short_id: Any) -> dict[str, Any]:
    return {
        "type": HANDSHAKE_TYPE,
        "call_short_id": str(call_short_id),
        "trace_id": message.get("trace_id"),
        "agent_id": message.get("agent_id"),
        "workspace_id": message.get("workspace_id"),
        "transport": message.get("transport"),
        "otel_correlation": dict(message.get("otel_correlation") or {}),
    }


def parse_trace_handshake(message: Any) -> Optional[dict[str, Any]]:
    """Return the normalized handshake, or ``None`` if ``message`` is not one.

    Accepts ``{"type": "efficientai_trace_handshake", "call_short_id": ...}`` and the
    older ``{"efficientai_call_short_id": ...}`` form.
    """
    if not isinstance(message, Mapping):
        return None

    if message.get("type") == HANDSHAKE_TYPE:
        call_short_id = message.get("call_short_id")
        return _normalized(message, call_short_id) if call_short_id else None

    legacy_id = message.get(LEGACY_CALL_SHORT_ID_KEY)
    if legacy_id:
        return _normalized(message, legacy_id)
    return None
