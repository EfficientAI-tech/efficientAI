"""Shared evaluator helpers."""

import random
from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models.database import Agent, Evaluator, Metric, Persona, Scenario, VoiceBundle


def generate_unique_evaluator_id(db: Session) -> str:
    """Generate a unique 6-digit evaluator ID."""
    max_attempts = 100
    for _ in range(max_attempts):
        evaluator_id = f"{random.randint(100000, 999999)}"
        existing = db.query(Evaluator).filter(Evaluator.evaluator_id == evaluator_id).first()
        if not existing:
            return evaluator_id
    raise HTTPException(status_code=500, detail="Failed to generate unique evaluator ID")


def is_custom_evaluator(evaluator: Evaluator) -> bool:
    """Legacy custom evaluators have no agent or only a custom_prompt."""
    return evaluator.agent_id is None or bool(evaluator.custom_prompt)


def _is_categorization_parent(metric: Metric) -> bool:
    return bool(metric.selection_mode and not metric.parent_metric_id)


def normalize_metric_ids_for_storage(
    db: Session,
    organization_id: UUID,
    metric_ids: List[str],
) -> List[str]:
    """Collapse categorization sub-label IDs to their parent metric ID."""
    if not metric_ids:
        return []

    id_set = {str(mid) for mid in metric_ids}
    metrics = db.query(Metric).filter(
        and_(
            Metric.organization_id == organization_id,
            Metric.id.in_([UUID(mid) for mid in id_set]),
        )
    ).all()
    metric_by_id = {str(m.id): m for m in metrics}

    parent_ids_needed = {
        str(m.parent_metric_id)
        for m in metrics
        if m.parent_metric_id is not None
    }
    if parent_ids_needed:
        parents = db.query(Metric).filter(
            and_(
                Metric.organization_id == organization_id,
                Metric.id.in_([UUID(pid) for pid in parent_ids_needed]),
            )
        ).all()
        for p in parents:
            metric_by_id[str(p.id)] = p

    normalized: set[str] = set()
    for mid in id_set:
        metric = metric_by_id.get(mid)
        if metric is None:
            continue
        if metric.parent_metric_id:
            parent = metric_by_id.get(str(metric.parent_metric_id))
            if parent and _is_categorization_parent(parent):
                normalized.add(str(parent.id))
            else:
                normalized.add(mid)
        else:
            normalized.add(mid)
    return sorted(normalized)


def expand_metric_ids_for_evaluation(
    db: Session,
    organization_id: UUID,
    metric_ids: Optional[List[str]],
) -> Optional[set[str]]:
    """Expand categorization parent IDs to their enabled child label IDs."""
    if metric_ids is None:
        return None
    if not metric_ids:
        return set()

    normalized = normalize_metric_ids_for_storage(db, organization_id, list(metric_ids))
    expanded: set[str] = set()

    parent_ids = [UUID(mid) for mid in normalized]
    parents = db.query(Metric).filter(
        and_(
            Metric.organization_id == organization_id,
            Metric.id.in_(parent_ids),
        )
    ).all()
    parent_by_id = {str(p.id): p for p in parents}

    categorization_parent_ids = [
        p.id for p in parents if _is_categorization_parent(p)
    ]
    children_by_parent: dict[str, list[Metric]] = {}
    if categorization_parent_ids:
        children = db.query(Metric).filter(
            and_(
                Metric.organization_id == organization_id,
                Metric.parent_metric_id.in_(categorization_parent_ids),
                Metric.enabled == True,
            )
        ).all()
        for child in children:
            children_by_parent.setdefault(str(child.parent_metric_id), []).append(child)

    for mid in normalized:
        parent = parent_by_id.get(mid)
        if parent and _is_categorization_parent(parent):
            for child in children_by_parent.get(mid, []):
                expanded.add(str(child.id))
        else:
            expanded.add(mid)
    return expanded


def validate_metric_ids(
    db: Session,
    organization_id: UUID,
    metric_ids: Optional[List[UUID]],
) -> Optional[List[str]]:
    """Validate and normalize metric IDs. Returns None when metric_ids is None."""
    if metric_ids is None:
        return None
    if not metric_ids:
        raise HTTPException(status_code=400, detail="Select at least one metric")

    metric_uuids = list({m for m in metric_ids})
    metrics = db.query(Metric).filter(
        and_(
            Metric.id.in_(metric_uuids),
            Metric.organization_id == organization_id,
        )
    ).all()
    if len(metrics) != len(metric_uuids):
        raise HTTPException(
            status_code=404,
            detail="One or more selected metrics were not found in this organization",
        )
    for m in metrics:
        if not m.enabled:
            raise HTTPException(
                status_code=400,
                detail=f"Metric '{m.name}' is disabled. Enable it before selecting it.",
            )
        surfaces = m.enabled_surfaces or []
        if surfaces and "agent" not in surfaces:
            raise HTTPException(
                status_code=400,
                detail=f"Metric '{m.name}' is not enabled for the agent surface.",
            )
    stored = [str(mid) for mid in metric_uuids]
    return normalize_metric_ids_for_storage(db, organization_id, stored)


def validate_agent_persona_tts(
    db: Session,
    agent: Agent,
    persona: Persona,
) -> None:
    if agent.voice_bundle_id and persona.tts_provider:
        voice_bundle = db.query(VoiceBundle).filter(VoiceBundle.id == agent.voice_bundle_id).first()
        if voice_bundle and voice_bundle.tts_provider:
            vb_provider = (
                voice_bundle.tts_provider.value
                if hasattr(voice_bundle.tts_provider, "value")
                else str(voice_bundle.tts_provider)
            ).lower()
            persona_provider = persona.tts_provider.lower()
            if vb_provider != persona_provider:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Persona '{persona.name}' uses TTS provider '{persona.tts_provider}' "
                        f"but agent '{agent.name}' voice bundle uses '{voice_bundle.tts_provider}'. "
                        f"The persona's TTS provider must match the agent's voice bundle TTS provider."
                    ),
                )


def load_suite_combinations(
    db: Session,
    suite_id: UUID,
    organization_id: UUID,
    workspace_id: UUID,
) -> List[Evaluator]:
    return (
        db.query(Evaluator)
        .filter(
            Evaluator.suite_id == suite_id,
            Evaluator.organization_id == organization_id,
            Evaluator.workspace_id == workspace_id,
        )
        .order_by(Evaluator.scenario_id)
        .all()
    )


def expand_suite_runs(combination_ids: List[UUID], runs_per_combination: int) -> List[UUID]:
    """Expand combination evaluator IDs for batch runs."""
    if runs_per_combination < 1:
        raise HTTPException(status_code=400, detail="runs_per_combination must be at least 1")
    expanded: List[UUID] = []
    for evaluator_id in combination_ids:
        for _ in range(runs_per_combination):
            expanded.append(evaluator_id)
    return expanded
