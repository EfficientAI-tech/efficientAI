"""Shared constants for imported production agent prompts and flowchart eligibility."""

from __future__ import annotations

from typing import Optional

IMPORTED_AGENT_TAG = "__imported_agent__"
AGENT_SYSTEM_PROMPT_TAG_PREFIX = "__agent_system_prompt__:"
AGENT_PROVIDER_PROMPT_TAG_PREFIX = "__agent_provider_prompt__:"


def partial_supports_flowchart(tags: Optional[list]) -> bool:
    """Return True when a prompt partial may use agent flowchart generation/mapping."""
    if not isinstance(tags, list):
        return False
    if IMPORTED_AGENT_TAG in tags:
        return True
    for tag in tags:
        if not isinstance(tag, str):
            continue
        if tag.startswith(AGENT_SYSTEM_PROMPT_TAG_PREFIX):
            return True
        if tag.startswith(AGENT_PROVIDER_PROMPT_TAG_PREFIX):
            return True
    return False
