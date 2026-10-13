"""Shared constants for imported production agent prompts and flowchart eligibility."""

from __future__ import annotations

from typing import Optional

IMPORTED_AGENT_TAG = "__imported_agent__"
AGENT_SYSTEM_PROMPT_TAG_PREFIX = "__agent_system_prompt__:"
AGENT_PROVIDER_PROMPT_TAG_PREFIX = "__agent_provider_prompt__:"
CALL_IMPORT_TAG_PREFIX = "__call_import__:"


def is_preserved_imported_agent_tag(tag: str) -> bool:
    if tag == IMPORTED_AGENT_TAG:
        return True
    if tag.startswith(AGENT_PROVIDER_PROMPT_TAG_PREFIX):
        return True
    if tag.startswith(CALL_IMPORT_TAG_PREFIX):
        return True
    return False


def merge_imported_agent_tags_on_update(
    existing: Optional[list],
    incoming: Optional[list],
) -> Optional[list]:
    """Keep import/provider link tags when clients send only __imported_agent__."""
    if incoming is None:
        return None
    existing_list = [t for t in (existing or []) if isinstance(t, str)]
    incoming_list = [t for t in incoming if isinstance(t, str)]
    if IMPORTED_AGENT_TAG not in incoming_list and IMPORTED_AGENT_TAG not in existing_list:
        return incoming_list
    preserved_existing = [t for t in existing_list if is_preserved_imported_agent_tag(t)]
    preserved_incoming = [t for t in incoming_list if is_preserved_imported_agent_tag(t)]
    user_incoming = [t for t in incoming_list if not is_preserved_imported_agent_tag(t)]
    if user_incoming:
        user = user_incoming
    elif preserved_incoming and set(preserved_incoming) >= set(preserved_existing):
        user = []
    else:
        user = [t for t in existing_list if not is_preserved_imported_agent_tag(t)]
    preserved = preserved_existing
    for tag in preserved_incoming:
        if tag not in preserved:
            preserved.append(tag)
    merged: list[str] = []
    seen: set[str] = set()
    for tag in preserved + user:
        if tag in seen:
            continue
        seen.add(tag)
        merged.append(tag)
    if IMPORTED_AGENT_TAG not in merged:
        merged.insert(0, IMPORTED_AGENT_TAG)
    return merged


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
