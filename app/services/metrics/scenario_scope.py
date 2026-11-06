"""Scenario scope for metrics: golden (all scenarios) vs linked to specific scenarios."""

from __future__ import annotations

from typing import Iterable, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import Metric, MetricScenarioAssignment, Scenario


def load_scenario_link_map(
    db: Session, metric_ids: Iterable[UUID]
) -> dict[UUID, frozenset[UUID]]:
    """Return metric_id -> linked scenario ids. Missing keys mean golden (no links)."""
    ids = list({UUID(str(i)) for i in metric_ids})
    if not ids:
        return {}
    rows = (
        db.query(MetricScenarioAssignment.metric_id, MetricScenarioAssignment.scenario_id)
        .filter(MetricScenarioAssignment.metric_id.in_(ids))
        .all()
    )
    out: dict[UUID, set[UUID]] = {}
    for mid, sid in rows:
        out.setdefault(mid, set()).add(sid)
    return {mid: frozenset(sids) for mid, sids in out.items()}


def scope_metric_id(metric: Metric) -> UUID:
    return metric.parent_metric_id or metric.id


def scenario_ids_for_response(metric: Metric) -> list[UUID]:
    """Scenario links for API responses; children inherit the parent's links."""
    if metric.parent_metric_id is not None:
        parent = metric.parent
        if parent is None:
            return []
        metric = parent
    return [s.id for s in sorted(metric.scoped_scenarios or [], key=lambda s: s.name or str(s.id))]


def is_golden_scope(link_map: dict[UUID, frozenset[UUID]], scope_id: UUID) -> bool:
    linked = link_map.get(scope_id)
    return linked is None or len(linked) == 0


def metric_applies_to_scenario(
    metric: Metric,
    scenario_id: Optional[UUID],
    *,
    link_map: dict[UUID, frozenset[UUID]],
) -> bool:
    if scenario_id is None:
        return True
    sid = scope_metric_id(metric)
    linked = link_map.get(sid)
    if linked is None or len(linked) == 0:
        return True
    return scenario_id in linked


def validate_scenario_links(
    db: Session,
    *,
    organization_id: UUID,
    metric: Metric,
    scenario_ids: list[UUID],
) -> None:
    if metric.parent_metric_id is not None:
        raise ValueError("Child metrics cannot have scenario links")
    if not scenario_ids:
        return
    unique = list(dict.fromkeys(scenario_ids))
    scenarios = (
        db.query(Scenario)
        .filter(
            Scenario.id.in_(unique),
            Scenario.organization_id == organization_id,
        )
        .all()
    )
    found = {s.id for s in scenarios}
    missing = [str(s) for s in unique if s not in found]
    if missing:
        raise ValueError(f"Scenarios not found: {', '.join(missing)}")
    if metric.workspace_id is not None:
        bad = [str(s.id) for s in scenarios if s.workspace_id != metric.workspace_id]
        if bad:
            raise ValueError(
                "Workspace-scoped metrics can only link to scenarios in the same workspace"
            )


def replace_metric_scenarios(
    db: Session,
    *,
    organization_id: UUID,
    metric: Metric,
    scenario_ids: Optional[list[UUID]],
) -> None:
    """Replace links. ``None`` leaves existing links unchanged; ``[]`` clears (golden)."""
    if scenario_ids is None:
        return
    validate_scenario_links(
        db, organization_id=organization_id, metric=metric, scenario_ids=scenario_ids
    )
    db.query(MetricScenarioAssignment).filter(
        MetricScenarioAssignment.metric_id == metric.id
    ).delete(synchronize_session=False)
    for sid in dict.fromkeys(scenario_ids):
        db.add(MetricScenarioAssignment(metric_id=metric.id, scenario_id=sid))
