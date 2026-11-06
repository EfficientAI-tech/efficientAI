"""Which LLM (or live endpoint) answers on each side of a simulation, for display."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.database import Agent
from app.services.agents.chat_connection import normalized_chat_connection_type
from app.services.agents.chat_llm_config import ResolvedSimulationLlm, resolve_simulation_llm
from app.services.agents.chat_production_leg import uses_live_production_leg

SOURCE_LABELS = {
    "main_llm": "agent production LLM",
    "test_llm": "agent test LLM",
    "voice_bundle": "voice bundle LLM",
    "simulation_run_override": "run override",
}


def describe_llm(llm: ResolvedSimulationLlm) -> dict[str, Any]:
    return {
        "kind": "llm",
        "provider": llm.provider.value,
        "model": llm.model,
        "source": llm.source,
        "label": f"{llm.provider.value}/{llm.model}",
        "source_label": SOURCE_LABELS.get(llm.source, llm.source),
    }


def describe_simulation_llms(
    db: Session,
    *,
    agent: Agent,
    production_override: Optional[ResolvedSimulationLlm] = None,
    test_override: Optional[ResolvedSimulationLlm] = None,
) -> dict[str, Optional[dict[str, Any]]]:
    """``{"production": ..., "test": ...}``; ``None`` for a side that can't be resolved."""

    def _resolve(leg: str, override: Optional[ResolvedSimulationLlm]):
        if override is not None:
            return describe_llm(override)
        try:
            return describe_llm(
                resolve_simulation_llm(
                    db, agent=agent, organization_id=agent.organization_id, leg=leg
                )
            )
        except ValueError:
            return None

    if uses_live_production_leg(agent):
        connection = normalized_chat_connection_type(agent)
        production = {
            "kind": "live",
            "provider": None,
            "model": None,
            "source": connection,
            "label": f"Live endpoint ({connection})",
            "source_label": "agent connection",
        }
    else:
        production = _resolve("main", production_override)
    return {"production": production, "test": _resolve("test", test_override)}
