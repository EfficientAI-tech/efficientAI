"""Read tools over the workspace's test-setup entities: agents, personas,
scenarios, evaluators and metrics.

Every query is filtered by the caller's organization and workspace from
``ToolContext``. Lists return compact summaries with a total, capped by
``limit``; full detail comes only from ``get_*`` tools, keeping model context small.
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.auth.capabilities import METRICS_VIEW, SIM_VIEW
from app.models.database import Agent, Evaluator, Metric, Persona, Scenario
from app.services.copilot.registry import CopilotTool, ToolContext, ToolError, register

PROMPT_PREVIEW_CHARS = 4_000
DESCRIPTION_PREVIEW_CHARS = 300


def _like(query: str) -> str:
    escaped = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _clip(value: Optional[str], limit: int) -> Optional[str]:
    if not value:
        return value
    return value if len(value) <= limit else value[:limit] + "…"


def _enum(value: Any) -> Any:
    return getattr(value, "value", value)


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if value is not None else None


class ListArgs(BaseModel):
    query: Optional[str] = Field(None, max_length=200, description="Case-insensitive name filter.")
    limit: int = Field(10, ge=1, le=25)


def _page(q, model, args: ListArgs) -> tuple[int, list]:
    if args.query and args.query.strip():
        q = q.filter(model.name.ilike(_like(args.query), escape="\\"))
    total = q.order_by(None).count()
    rows = q.order_by(model.updated_at.desc().nullslast(), model.id).limit(args.limit).all()
    return total, rows


def _resolve_agent(db: Session, ctx: ToolContext, ref: str) -> Agent:
    q = db.query(Agent).filter(
        Agent.organization_id == ctx.organization_id,
        Agent.workspace_id == ctx.workspace_id,
    )
    ref = ref.strip()
    try:
        agent = q.filter(Agent.id == UUID(ref)).first()
    except ValueError:
        agent = q.filter(Agent.agent_id == ref).first()
    if agent is None:
        raise ToolError(f"No agent {ref!r} in this workspace. Use list_agents to find it.")
    return agent


# --- agents -----------------------------------------------------------------


def _list_agents(ctx: ToolContext, db: Session, args: ListArgs) -> dict:
    q = db.query(Agent).filter(
        Agent.organization_id == ctx.organization_id,
        Agent.workspace_id == ctx.workspace_id,
    )
    total, rows = _page(q, Agent, args)
    return {
        "total": total,
        "agents": [
            {
                "id": str(a.id),
                "agent_id": a.agent_id,
                "name": a.name,
                "call_medium": _enum(a.call_medium),
                "call_type": _enum(a.call_type),
                "language": _enum(a.language),
                "updated_at": _iso(a.updated_at),
                "link": f"/agents/{a.id}",
            }
            for a in rows
        ],
    }


class AgentRef(BaseModel):
    agent: str = Field(..., max_length=64, description="Agent UUID or 6-digit agent id.")


def _get_agent(ctx: ToolContext, db: Session, args: AgentRef) -> dict:
    agent = _resolve_agent(db, ctx, args.agent)
    scenario_count = (
        db.query(func.count(Scenario.id))
        .filter(Scenario.workspace_id == ctx.workspace_id, Scenario.agent_id == agent.id)
        .scalar()
    )
    evaluator_count = (
        db.query(func.count(Evaluator.id))
        .filter(Evaluator.workspace_id == ctx.workspace_id, Evaluator.agent_id == agent.id)
        .scalar()
    )
    return {
        "id": str(agent.id),
        "agent_id": agent.agent_id,
        "name": agent.name,
        "description": _clip(agent.description, DESCRIPTION_PREVIEW_CHARS),
        "call_medium": _enum(agent.call_medium),
        "call_type": _enum(agent.call_type),
        "language": _enum(agent.language),
        "production_prompt": _clip(agent.provider_prompt, PROMPT_PREVIEW_CHARS),
        "has_test_agent_template": bool(agent.test_agent_template),
        "scenario_count": int(scenario_count or 0),
        "evaluator_count": int(evaluator_count or 0),
        "created_at": _iso(agent.created_at),
        "link": f"/agents/{agent.id}",
    }


# --- personas / scenarios / evaluators ---------------------------------------


def _list_personas(ctx: ToolContext, db: Session, args: ListArgs) -> dict:
    q = db.query(Persona).filter(
        Persona.organization_id == ctx.organization_id,
        Persona.workspace_id == ctx.workspace_id,
    )
    total, rows = _page(q, Persona, args)
    return {
        "total": total,
        "personas": [
            {
                "id": str(p.id),
                "name": p.name,
                "description": _clip(p.description, DESCRIPTION_PREVIEW_CHARS),
                "simulation_medium": _enum(p.simulation_medium),
                "gender": _enum(p.gender),
            }
            for p in rows
        ],
    }


class ScenarioListArgs(ListArgs):
    agent: Optional[str] = Field(None, max_length=64, description="Only this agent's scenarios.")


def _list_scenarios(ctx: ToolContext, db: Session, args: ScenarioListArgs) -> dict:
    q = db.query(Scenario).filter(
        Scenario.organization_id == ctx.organization_id,
        Scenario.workspace_id == ctx.workspace_id,
    )
    if args.agent:
        q = q.filter(Scenario.agent_id == _resolve_agent(db, ctx, args.agent).id)
    total, rows = _page(q, Scenario, args)
    return {
        "total": total,
        "scenarios": [
            {
                "id": str(s.id),
                "name": s.name,
                "agent_id": str(s.agent_id) if s.agent_id else None,
                "description": _clip(s.description, DESCRIPTION_PREVIEW_CHARS),
            }
            for s in rows
        ],
    }


def _list_evaluators(ctx: ToolContext, db: Session, args: ScenarioListArgs) -> dict:
    q = db.query(Evaluator).filter(
        Evaluator.organization_id == ctx.organization_id,
        Evaluator.workspace_id == ctx.workspace_id,
    )
    if args.agent:
        q = q.filter(Evaluator.agent_id == _resolve_agent(db, ctx, args.agent).id)
    total, rows = _page(q, Evaluator, args)
    return {
        "total": total,
        "evaluators": [
            {
                "id": str(e.id),
                "evaluator_id": e.evaluator_id,
                "name": e.name,
                "agent_id": str(e.agent_id) if e.agent_id else None,
                "persona_id": str(e.persona_id) if e.persona_id else None,
                "scenario_id": str(e.scenario_id) if e.scenario_id else None,
                "metric_count": len(e.metric_ids or []),
            }
            for e in rows
        ],
    }


# --- metrics -----------------------------------------------------------------


def _list_metrics(ctx: ToolContext, db: Session, args: ListArgs) -> dict:
    # Workspace metrics plus org-shared ones (workspace_id IS NULL).
    q = db.query(Metric).filter(
        Metric.organization_id == ctx.organization_id,
        or_(Metric.workspace_id == ctx.workspace_id, Metric.workspace_id.is_(None)),
    )
    total, rows = _page(q, Metric, args)
    return {
        "total": total,
        "metrics": [
            {
                "id": str(m.id),
                "name": m.name,
                "type": _enum(m.metric_type),
                "data_type": m.custom_data_type,
                "enabled": bool(m.enabled),
                "shared_across_workspaces": m.workspace_id is None,
                "description": _clip(m.description, DESCRIPTION_PREVIEW_CHARS),
            }
            for m in rows
        ],
    }


register(CopilotTool(
    name="list_agents",
    description="List agents in the current workspace, newest first. Filter by name with `query`.",
    args_model=ListArgs,
    handler=_list_agents,
    capability=SIM_VIEW,
))
register(CopilotTool(
    name="get_agent",
    description="Get one agent's details, including its production prompt (truncated) and how many scenarios and evaluators it has.",
    args_model=AgentRef,
    handler=_get_agent,
    capability=SIM_VIEW,
))
register(CopilotTool(
    name="list_personas",
    description="List simulated-caller personas in the current workspace. Filter by name with `query`.",
    args_model=ListArgs,
    handler=_list_personas,
    capability=SIM_VIEW,
))
register(CopilotTool(
    name="list_scenarios",
    description="List test scenarios in the current workspace, optionally only one agent's.",
    args_model=ScenarioListArgs,
    handler=_list_scenarios,
    capability=SIM_VIEW,
))
register(CopilotTool(
    name="list_evaluators",
    description="List evaluators (agent + persona + scenario + metrics test configurations) in the current workspace, optionally only one agent's.",
    args_model=ScenarioListArgs,
    handler=_list_evaluators,
    capability=SIM_VIEW,
))
register(CopilotTool(
    name="list_metrics",
    description="List evaluation metrics available in the current workspace (including org-shared ones), with their type. Use it to resolve a metric name the user mentions.",
    args_model=ListArgs,
    handler=_list_metrics,
    capability=METRICS_VIEW,
))
