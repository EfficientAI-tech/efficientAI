"""Wrap voice-oriented production prompts for text chat LLM simulation."""

from __future__ import annotations

CHAT_SIMULATION_PREAMBLE = """## Text chat mode (simulation)

The instructions below may describe a phone or voice assistant. For this run you are in a **live text chat** (typed messages only).

- Reply as chat messages, not spoken dialogue. Do not reference phones, calls, holding, or speaking aloud.
- Use a brief chat greeting when appropriate (e.g. "Hi, I'm Riley from Wellness Partners. How can I help you today?").
- Keep the same business goals, policies, and scheduling rules from the instructions.
- One question per message when gathering information; stay concise (1-4 sentences)."""


def adapt_production_prompt_for_chat_simulation(production_prompt: str) -> str:
    body = (production_prompt or "").strip()
    if not body:
        return CHAT_SIMULATION_PREAMBLE
    return f"{CHAT_SIMULATION_PREAMBLE}\n\n---\n\n{body}"
