"""Shared system prompts for evaluator LLM simulation (avoids circular imports)."""

from __future__ import annotations

from app.models.database import Agent
from app.services.testing.test_agent_simulation_prompt import (
    is_chat_agent,
    production_prompt_for_simulation,
)


def build_agent_system_prompt(agent: Agent) -> str:
    agent_name = (agent.name or "Voice AI Agent").strip()
    base = production_prompt_for_simulation(agent)
    if is_chat_agent(agent):
        return (
            f"You are {agent_name}, the production chat agent.\n\n"
            f"Your instructions:\n{base}\n\n"
            "Reply in plain text as in a live chat. "
            "Keep replies concise (1-4 sentences). "
            "Output ONLY the message text — no markdown headers or stage directions."
        )
    return (
        f"You are {agent_name}, a voice AI agent on a live phone call.\n\n"
        f"Your instructions:\n{base}\n\n"
        "Respond naturally in 1-3 sentences as on a phone call. "
        "Respond ONLY with what you would say — no stage directions."
    )
