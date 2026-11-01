"""Agent and scenario scope for metrics (golden = no links on that dimension)."""

from __future__ import annotations

from typing import Iterable, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import Agent, Metric, MetricAgentAssignment, MetricScenarioAssignment, Scenario
from app.services.metrics.scenario_scope import (
    is_golden_scope,
    load_scenario_link_map,
    metric_applies_to_scenario,
    replace_metric_scenarios,
    scenario_ids_for_response,
    scope_metric_id,
    validate_scenario_links,
)

__all__ = [
    "agent_ids_for_response",
    "applicable_metrics",
    "is_fully_golden",
    "is_golden_scope",
    "load_agent_link_map",
    "load_scenario_link_map",
    "metric_applies_to_agent",
    "metric_applies_to_scenario",
    "replace_metric_agents",
    "replace_metric_scenarios",
    "scenario_ids_for_response",
    "scope_metric_id",
    "validate_agent_links",
    "validate_scenario_links",
]


def load_agent_link_map(
    db: Session, metric_ids: Iterable[UUID]
) -> dict[UUID, frozenset[UUID]]:
    ids = list({UUID(str(i)) for i in metric_ids})
    if not ids:
        return {}
    rows = (
        db.query(MetricAgentAssignment.metric_id, MetricAgentAssignment.agent_id)
        .filter(MetricAgentAssignment.metric_id.in_(ids))
        .all()
    )
    out: dict[UUID, set[UUID]] = {}
    for mid, aid in rows:
        out.setdefault(mid, set()).add(aid)
    return {mid: frozenset(aids) for mid, aids in out.items()}


def agent_ids_for_response(metric: Metric) -> list[UUID]:
    if metric.parent_metric_id is not None:
        parent = metric.parent
        if parent is None:
            return []
        metric = parent
    return [a.id for a in sorted(metric.scoped_agents or [], key=lambda a: a.name or str(a.id))]


def metric_applies_to_agent(
    metric: Metric,
    agent_id: Optional[UUID],
    *,
    link_map: dict[UUID, frozenset[UUID]],
) -> bool:
    if agent_id is None:
        return True
    sid = scope_metric_id(metric)
    linked = link_map.get(sid)
    if linked is None or len(linked) == 0:
        return True
    return agent_id in linked


def is_fully_golden(
    scope_id: UUID,
    *,
    agent_link_map: dict[UUID, frozenset[UUID]],
    scenario_link_map: dict[UUID, frozenset[UUID]],
) -> bool:
    return is_golden_scope(agent_link_map, scope_id) and is_golden_scope(
        scenario_link_map, scope_id
    )


def applicable_metrics(
    metrics: list[Metric],
    *,
    agent_id: Optional[UUID] = None,
    scenario_id: Optional[UUID] = None,
    db: Optional[Session] = None,
    agent_link_map: Optional[dict[UUID, frozenset[UUID]]] = None,
    scenario_link_map: Optional[dict[UUID, frozenset[UUID]]] = None,
) -> list[Metric]:
    if agent_id is None and scenario_id is None:
        return metrics
    scope_ids = {scope_metric_id(m) for m in metrics}
    if agent_link_map is None or scenario_link_map is None:
        if db is None:
            raise ValueError("db or both link maps are required when filtering by scope")
        if agent_link_map is None:
            agent_link_map = load_agent_link_map(db, scope_ids)
        if scenario_link_map is None:
            scenario_link_map = load_scenario_link_map(db, scope_ids)
    return [
        m
        for m in metrics
        if metric_applies_to_agent(m, agent_id, link_map=agent_link_map)
        and metric_applies_to_scenario(m, scenario_id, link_map=scenario_link_map)
    ]


def validate_agent_links(
    db: Session,
    *,
    organization_id: UUID,
    metric: Metric,
    agent_ids: list[UUID],
) -> None:
    if metric.parent_metric_id is not None:
        raise ValueError("Child metrics cannot have agent links")
    if not agent_ids:
        return
    unique = list(dict.fromkeys(agent_ids))
    agents = (
        db.query(Agent)
        .filter(Agent.id.in_(unique), Agent.organization_id == organization_id)
        .all()
    )
    found = {a.id for a in agents}
    missing = [str(a) for a in unique if a not in found]
    if missing:
        raise ValueError(f"Agents not found: {', '.join(missing)}")
    if metric.workspace_id is not None:
        bad = [str(a.id) for a in agents if a.workspace_id != metric.workspace_id]
        if bad:
            raise ValueError(
                "Workspace-scoped metrics can only link to agents in the same workspace"
            )


def replace_metric_agents(
    db: Session,
    *,
    organization_id: UUID,
    metric: Metric,
    agent_ids: Optional[list[UUID]],
) -> None:
    if agent_ids is None:
        return
    validate_agent_links(
        db, organization_id=organization_id, metric=metric, agent_ids=agent_ids
    )
    db.query(MetricAgentAssignment).filter(
        MetricAgentAssignment.metric_id == metric.id
    ).delete(synchronize_session=False)
    for aid in dict.fromkeys(agent_ids):
        db.add(MetricAgentAssignment(metric_id=metric.id, agent_id=aid))
