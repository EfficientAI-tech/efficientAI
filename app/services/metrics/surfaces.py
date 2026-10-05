"""Metric evaluation surfaces (where a metric may run)."""

from __future__ import annotations

from typing import Any, FrozenSet, Optional

SURFACE_VOICE_AGENT = "agent"
SURFACE_CHAT_AGENT = "chat_agent"
SURFACE_VOICE_PLAYGROUND = "voice_playground"

ALLOWED_METRIC_SURFACES: FrozenSet[str] = frozenset(
    {
        SURFACE_VOICE_AGENT,
        SURFACE_CHAT_AGENT,
        SURFACE_VOICE_PLAYGROUND,
    }
)


def metric_eval_surface_for_call_medium(call_medium: Any) -> str:
    raw = call_medium.value if hasattr(call_medium, "value") else call_medium
    if str(raw or "").lower() == "chat":
        return SURFACE_CHAT_AGENT
    return SURFACE_VOICE_AGENT


def metric_enabled_for_eval_surface(
    enabled_surfaces: Optional[list],
    eval_surface: str,
) -> bool:
    """Whether an enabled metric applies to voice agent vs chat agent eval runs."""
    surfaces = enabled_surfaces or []
    if not surfaces:
        return eval_surface in (SURFACE_VOICE_AGENT, SURFACE_CHAT_AGENT)
    return eval_surface in surfaces
