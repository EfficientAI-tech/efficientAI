"""Metric selection helpers for Metrics Studio runs."""

from __future__ import annotations

from typing import Dict, List, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import Metric


def expand_studio_metric_selection(
    db: Session,
    org_id: UUID,
    selected_ids: List[UUID],
) -> Tuple[List[Metric], Dict[UUID, List[Metric]]]:
    """Like call-import metric expansion but allows draft/disabled metrics."""
    if not selected_ids:
        return [], {}

    requested = list(selected_ids)
    initial_rows = (
        db.query(Metric)
        .filter(
            Metric.organization_id == org_id,
            Metric.id.in_(requested),
        )
        .all()
    )
    initial_by_id = {row.id: row for row in initial_rows}

    parent_ids_requested = {
        m.id for m in initial_rows if m.selection_mode and not m.parent_metric_id
    }
    explicit_children_by_parent: Dict[UUID, List[Metric]] = {}
    for m in initial_rows:
        if m.parent_metric_id and m.parent_metric_id in parent_ids_requested:
            explicit_children_by_parent.setdefault(m.parent_metric_id, []).append(m)

    parents_needing_full_expansion = [
        pid for pid in parent_ids_requested if pid not in explicit_children_by_parent
    ]
    auto_expanded_children: Dict[UUID, List[Metric]] = {}
    if parents_needing_full_expansion:
        for pid in parents_needing_full_expansion:
            child_rows = (
                db.query(Metric)
                .filter(
                    Metric.organization_id == org_id,
                    Metric.parent_metric_id == pid,
                )
                .order_by(Metric.created_at.asc())
                .all()
            )
            auto_expanded_children[pid] = child_rows

    parent_to_children: Dict[UUID, List[Metric]] = {}
    for pid in parent_ids_requested:
        children = explicit_children_by_parent.get(pid) or auto_expanded_children.get(
            pid, []
        )
        parent_to_children[pid] = list(children)

    effective: List[Metric] = []
    seen: set[UUID] = set()
    for mid in requested:
        m = initial_by_id.get(mid)
        if m is None:
            continue
        if m.selection_mode and not m.parent_metric_id:
            for child in parent_to_children.get(m.id, []):
                if child.id in seen:
                    continue
                seen.add(child.id)
                effective.append(child)
        elif m.parent_metric_id is None or m.parent_metric_id not in parent_ids_requested:
            if m.id in seen:
                continue
            seen.add(m.id)
            effective.append(m)

    return effective, parent_to_children


def load_studio_run_metrics(
    db: Session,
    organization_id: UUID,
    metric_ids: List[UUID],
) -> List[Metric]:
    if not metric_ids:
        return []
    return (
        db.query(Metric)
        .filter(
            Metric.organization_id == organization_id,
            Metric.id.in_(metric_ids),
        )
        .all()
    )
