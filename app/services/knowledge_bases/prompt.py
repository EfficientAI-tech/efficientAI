"""System prompt additions for knowledge-base-enabled agents."""

from __future__ import annotations

KB_SYSTEM_APPENDIX = (
    "\n\nYou have access to organization knowledge bases. "
    "On voice calls, relevant document excerpts are retrieved automatically from what the "
    "other party says; you may also call search_knowledge_base when you need more detail. "
    "Prefer retrieved or tool results over guessing, and cite the document name when answering."
)

# Playground / simulated caller: production speaks as "user"; caller must use injected passages.
CALLER_KB_VOICE_APPENDIX = (
    "\n\nWhen a system message contains 'Retrieved passages' and the production agent's latest "
    "message asks a factual question those passages answer, answer from the passages first "
    "(accurately and briefly). You may then continue your persona and scenario."
)


def append_knowledge_base_instructions(
    system_prompt: str,
    *,
    simulated_caller: bool = False,
) -> str:
    base = (system_prompt or "").strip()
    appendix = KB_SYSTEM_APPENDIX
    if simulated_caller:
        appendix = appendix + CALLER_KB_VOICE_APPENDIX
    if not base:
        return appendix.strip()
    if "search_knowledge_base" in base and "Retrieved passages" in base:
        return base
    return base + appendix
