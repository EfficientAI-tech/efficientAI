"""Evaluator suite business logic."""

import random
from typing import Dict, List, Optional, Set, Tuple
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.services.evaluators.evaluator_helpers import (
    generate_unique_evaluator_id,
    expand_suite_runs,
    load_suite_combinations,
    validate_agent_persona_tts,
    validate_metric_ids,
)
from app.models.database import (
    Agent,
    Evaluator,
    EvaluatorResult,
    EvaluatorSuite,
    Persona,
    Scenario,
)
from app.models.schemas import (
    EvaluatorSuiteCombinationResponse,
    EvaluatorSuiteCreate,
    EvaluatorSuitePersonaSummary,
    EvaluatorSuiteResponse,
    EvaluatorSuiteUpdate,
)


def _agent_suite_count(
    db: Session,
    workspace_id: UUID,
    agent_id: UUID,
) -> int:
    return (
        db.query(EvaluatorSuite)
        .filter(
            EvaluatorSuite.workspace_id == workspace_id,
            EvaluatorSuite.agent_id == agent_id,
        )
        .count()
    )


def _resolve_create_persona_ids(data: EvaluatorSuiteCreate) -> List[UUID]:
    if data.persona_ids:
        persona_ids = list(dict.fromkeys(data.persona_ids))
        if not persona_ids:
            raise HTTPException(status_code=400, detail="persona_ids must contain at least one persona")
        return persona_ids
    if data.persona_id:
        return [data.persona_id]
    raise HTTPException(status_code=400, detail="Either persona_id or persona_ids is required")


def _distinct_ids_in_order(values: List[Optional[UUID]]) -> List[UUID]:
    seen: Set[UUID] = set()
    ordered: List[UUID] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _suite_persona_ids(combinations: List[Evaluator], primary_persona_id: UUID) -> List[UUID]:
    combo_persona_ids = _distinct_ids_in_order([c.persona_id for c in combinations])
    if primary_persona_id in combo_persona_ids:
        return [primary_persona_id] + [pid for pid in combo_persona_ids if pid != primary_persona_id]
    return combo_persona_ids


def _suite_scenario_ids(combinations: List[Evaluator]) -> List[UUID]:
    return _distinct_ids_in_order([c.scenario_id for c in combinations])


def _load_personas_by_id(db: Session, persona_ids: List[UUID]) -> Dict[UUID, Persona]:
    if not persona_ids:
        return {}
    personas = db.query(Persona).filter(Persona.id.in_(persona_ids)).all()
    return {p.id: p for p in personas}


def _validate_personas_for_agent(
    db: Session,
    agent: Agent,
    persona_ids: List[UUID],
    organization_id: UUID,
    workspace_id: UUID,
) -> List[Persona]:
    personas = db.query(Persona).filter(
        and_(
            Persona.id.in_(persona_ids),
            Persona.organization_id == organization_id,
            Persona.workspace_id == workspace_id,
        )
    ).all()
    if len(personas) != len(set(persona_ids)):
        raise HTTPException(status_code=404, detail="One or more personas not found")
    personas_by_id = {p.id: p for p in personas}
    ordered = [personas_by_id[pid] for pid in persona_ids]
    for persona in ordered:
        validate_agent_persona_tts(db, agent, persona)
    return ordered


def _build_suite_response(
    db: Session,
    suite: EvaluatorSuite,
    combinations: Optional[List[Evaluator]] = None,
) -> EvaluatorSuiteResponse:
    if combinations is None:
        combinations = load_suite_combinations(
            db, suite.id, suite.organization_id, suite.workspace_id
        )

    agent = db.query(Agent).filter(Agent.id == suite.agent_id).first()
    persona_ids = _suite_persona_ids(combinations, suite.persona_id)
    personas_by_id = _load_personas_by_id(db, persona_ids)
    primary_persona = personas_by_id.get(suite.persona_id)

    scenario_ids = [c.scenario_id for c in combinations if c.scenario_id]
    scenarios_by_id = {}
    if scenario_ids:
        scenarios = db.query(Scenario).filter(Scenario.id.in_(scenario_ids)).all()
        scenarios_by_id = {s.id: s for s in scenarios}

    combo_responses = []
    for combo in combinations:
        scenario = scenarios_by_id.get(combo.scenario_id) if combo.scenario_id else None
        combo_persona = personas_by_id.get(combo.persona_id) if combo.persona_id else None
        combo_responses.append(
            EvaluatorSuiteCombinationResponse(
                id=combo.id,
                evaluator_id=combo.evaluator_id,
                persona_id=combo.persona_id,
                persona_name=combo_persona.name if combo_persona else None,
                scenario_id=combo.scenario_id,
                scenario_name=scenario.name if scenario else None,
                scenario_description=scenario.description if scenario else None,
                scenario_required_info=scenario.required_info if scenario else None,
            )
        )

    persona_summaries = [
        EvaluatorSuitePersonaSummary(
            id=pid,
            name=personas_by_id[pid].name if pid in personas_by_id else None,
        )
        for pid in persona_ids
    ]

    return EvaluatorSuiteResponse(
        id=suite.id,
        organization_id=suite.organization_id,
        name=suite.name,
        agent_id=suite.agent_id,
        persona_id=suite.persona_id,
        persona_ids=persona_ids,
        personas=persona_summaries,
        agent_name=agent.name if agent else None,
        persona_name=primary_persona.name if primary_persona else None,
        agent_call_type=getattr(agent, "call_type", None) if agent else None,
        agent_call_medium=getattr(agent, "call_medium", None) if agent else None,
        metric_ids=suite.metric_ids,
        llm_provider=suite.llm_provider,
        llm_model=suite.llm_model,
        llm_config=suite.llm_config,
        tags=suite.tags,
        default_runs_per_combination=suite.default_runs_per_combination or 1,
        round_robin_index=suite.round_robin_index or 0,
        is_active=bool(getattr(suite, "is_active", False)),
        agent_suite_count=_agent_suite_count(db, suite.workspace_id, suite.agent_id),
        combination_count=len(combo_responses),
        combinations=combo_responses,
        created_at=suite.created_at,
        updated_at=suite.updated_at,
        created_by=suite.created_by,
    )


def get_suite_or_404(
    db: Session,
    suite_id: UUID,
    organization_id: UUID,
    workspace_id: UUID,
) -> EvaluatorSuite:
    suite = (
        db.query(EvaluatorSuite)
        .filter(
            EvaluatorSuite.id == suite_id,
            EvaluatorSuite.organization_id == organization_id,
            EvaluatorSuite.workspace_id == workspace_id,
        )
        .first()
    )
    if not suite:
        raise HTTPException(status_code=404, detail="Evaluator suite not found")
    return suite


def _validate_scenarios_for_agent(
    scenarios: List[Scenario],
    agent_id: UUID,
) -> None:
    for scenario in scenarios:
        if scenario.agent_id != agent_id:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Scenario '{scenario.name}' is not linked to the selected agent. "
                    "Link the scenario to this agent before adding it to the suite."
                ),
            )


def _create_child_evaluators(
    db: Session,
    suite: EvaluatorSuite,
    persona_ids: List[UUID],
    scenario_ids: List[UUID],
    validated_metric_ids: Optional[List[str]],
) -> List[Evaluator]:
    evaluators = []
    for persona_id in persona_ids:
        for scenario_id in scenario_ids:
            evaluator_id = generate_unique_evaluator_id(db)
            evaluator = Evaluator(
                evaluator_id=evaluator_id,
                organization_id=suite.organization_id,
                workspace_id=suite.workspace_id,
                suite_id=suite.id,
                name=suite.name,
                agent_id=suite.agent_id,
                persona_id=persona_id,
                scenario_id=scenario_id,
                metric_ids=validated_metric_ids,
                llm_provider=suite.llm_provider,
                llm_model=suite.llm_model,
                llm_config=suite.llm_config,
                tags=suite.tags,
            )
            db.add(evaluator)
            evaluators.append(evaluator)
    return evaluators


def _delete_combination_rows(db: Session, combos: List[Evaluator]) -> None:
    for combo in combos:
        db.query(EvaluatorResult).filter(EvaluatorResult.evaluator_id == combo.id).update(
            {EvaluatorResult.evaluator_id: None}, synchronize_session=False
        )
        db.delete(combo)


def _sync_suite_grid(
    db: Session,
    suite: EvaluatorSuite,
    persona_ids: List[UUID],
    scenario_ids: List[UUID],
) -> List[Evaluator]:
    if not persona_ids:
        raise HTTPException(status_code=400, detail="At least one persona is required")
    if not scenario_ids:
        raise HTTPException(status_code=400, detail="At least one scenario is required")

    existing = load_suite_combinations(db, suite.id, suite.organization_id, suite.workspace_id)
    desired_pairs = {(pid, sid) for pid in persona_ids for sid in scenario_ids}

    to_delete = [c for c in existing if (c.persona_id, c.scenario_id) not in desired_pairs]
    if to_delete:
        _delete_combination_rows(db, to_delete)
        db.flush()

    still_existing = {
        (c.persona_id, c.scenario_id)
        for c in load_suite_combinations(db, suite.id, suite.organization_id, suite.workspace_id)
    }
    missing_pairs = [
        (pid, sid)
        for pid in persona_ids
        for sid in scenario_ids
        if (pid, sid) not in still_existing
    ]

    if missing_pairs:
        for persona_id, scenario_id in missing_pairs:
            evaluator_id = generate_unique_evaluator_id(db)
            evaluator = Evaluator(
                evaluator_id=evaluator_id,
                organization_id=suite.organization_id,
                workspace_id=suite.workspace_id,
                suite_id=suite.id,
                name=suite.name,
                agent_id=suite.agent_id,
                persona_id=persona_id,
                scenario_id=scenario_id,
                metric_ids=suite.metric_ids,
                llm_provider=suite.llm_provider,
                llm_model=suite.llm_model,
                llm_config=suite.llm_config,
                tags=suite.tags,
            )
            db.add(evaluator)

    suite.persona_id = persona_ids[0]
    db.flush()
    return load_suite_combinations(db, suite.id, suite.organization_id, suite.workspace_id)


def create_evaluator_suite(
    db: Session,
    organization_id: UUID,
    workspace_id: UUID,
    data: EvaluatorSuiteCreate,
) -> EvaluatorSuiteResponse:
    persona_ids = _resolve_create_persona_ids(data)

    agent = db.query(Agent).filter(
        and_(
            Agent.id == data.agent_id,
            Agent.organization_id == organization_id,
            Agent.workspace_id == workspace_id,
        )
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    _validate_personas_for_agent(db, agent, persona_ids, organization_id, workspace_id)

    scenarios = db.query(Scenario).filter(
        and_(
            Scenario.id.in_(data.scenario_ids),
            Scenario.organization_id == organization_id,
            Scenario.workspace_id == workspace_id,
        )
    ).all()
    if len(scenarios) != len(set(data.scenario_ids)):
        raise HTTPException(status_code=404, detail="One or more scenarios not found")

    _validate_scenarios_for_agent(scenarios, data.agent_id)

    validated_metric_ids = validate_metric_ids(db, organization_id, data.metric_ids)
    scenario_ids = list(dict.fromkeys(data.scenario_ids))

    existing_for_agent = (
        db.query(EvaluatorSuite)
        .filter(
            EvaluatorSuite.workspace_id == workspace_id,
            EvaluatorSuite.agent_id == data.agent_id,
        )
        .count()
    )

    suite = EvaluatorSuite(
        organization_id=organization_id,
        workspace_id=workspace_id,
        name=data.name,
        agent_id=data.agent_id,
        persona_id=persona_ids[0],
        metric_ids=validated_metric_ids,
        llm_provider=data.llm_provider.value if data.llm_provider else None,
        llm_model=data.llm_model,
        llm_config=data.llm_config,
        tags=data.tags,
        default_runs_per_combination=data.default_runs_per_combination,
        round_robin_index=0,
        is_active=existing_for_agent == 0,
    )
    db.add(suite)
    db.flush()

    evaluators = _create_child_evaluators(
        db, suite, persona_ids, scenario_ids, validated_metric_ids
    )
    db.commit()
    db.refresh(suite)
    for ev in evaluators:
        db.refresh(ev)

    return _build_suite_response(db, suite, evaluators)


def update_evaluator_suite(
    db: Session,
    suite: EvaluatorSuite,
    data: EvaluatorSuiteUpdate,
) -> EvaluatorSuiteResponse:
    if data.name is not None:
        suite.name = data.name
    if data.tags is not None:
        suite.tags = data.tags
    if data.default_runs_per_combination is not None:
        suite.default_runs_per_combination = data.default_runs_per_combination
    if data.llm_provider is not None:
        suite.llm_provider = data.llm_provider.value
    if data.llm_model is not None:
        suite.llm_model = data.llm_model
    if data.llm_config is not None:
        suite.llm_config = data.llm_config

    llm_changed = (
        data.llm_provider is not None
        or data.llm_model is not None
        or data.llm_config is not None
    )

    if data.metric_ids is not None:
        if not data.metric_ids:
            validated = None
        else:
            validated = validate_metric_ids(db, suite.organization_id, data.metric_ids)
        suite.metric_ids = validated
        combinations = load_suite_combinations(
            db, suite.id, suite.organization_id, suite.workspace_id
        )
        for combo in combinations:
            combo.metric_ids = validated

    if llm_changed:
        combinations = load_suite_combinations(
            db, suite.id, suite.organization_id, suite.workspace_id
        )
        for combo in combinations:
            if data.llm_provider is not None:
                combo.llm_provider = suite.llm_provider
            if data.llm_model is not None:
                combo.llm_model = suite.llm_model
            if data.llm_config is not None:
                combo.llm_config = suite.llm_config

    db.commit()
    db.refresh(suite)
    return _build_suite_response(db, suite)


def add_scenarios_to_suite(
    db: Session,
    suite: EvaluatorSuite,
    scenario_ids: List[UUID],
) -> EvaluatorSuiteResponse:
    existing = load_suite_combinations(db, suite.id, suite.organization_id, suite.workspace_id)
    existing_scenario_ids = {c.scenario_id for c in existing}
    new_ids = [sid for sid in scenario_ids if sid not in existing_scenario_ids]
    if not new_ids:
        return _build_suite_response(db, suite)

    scenarios = db.query(Scenario).filter(
        and_(
            Scenario.id.in_(new_ids),
            Scenario.organization_id == suite.organization_id,
            Scenario.workspace_id == suite.workspace_id,
        )
    ).all()
    if len(scenarios) != len(new_ids):
        raise HTTPException(status_code=404, detail="One or more scenarios not found")

    _validate_scenarios_for_agent(scenarios, suite.agent_id)

    persona_ids = _suite_persona_ids(existing, suite.persona_id)
    if not persona_ids:
        persona_ids = [suite.persona_id]

    _create_child_evaluators(db, suite, persona_ids, new_ids, suite.metric_ids)
    db.commit()
    db.refresh(suite)
    return _build_suite_response(db, suite)


def remove_scenario_from_suite(
    db: Session,
    suite: EvaluatorSuite,
    scenario_id: UUID,
) -> EvaluatorSuiteResponse:
    combos = (
        db.query(Evaluator)
        .filter(
            Evaluator.suite_id == suite.id,
            Evaluator.scenario_id == scenario_id,
        )
        .all()
    )
    if not combos:
        raise HTTPException(status_code=404, detail="Scenario combination not found in suite")

    remaining_scenario_ids = {
        c.scenario_id
        for c in load_suite_combinations(db, suite.id, suite.organization_id, suite.workspace_id)
        if c.scenario_id and c.scenario_id != scenario_id
    }
    if not remaining_scenario_ids:
        raise HTTPException(status_code=400, detail="Cannot remove the last scenario from a suite")

    _delete_combination_rows(db, combos)
    db.commit()
    db.refresh(suite)
    return _build_suite_response(db, suite)


def add_personas_to_suite(
    db: Session,
    suite: EvaluatorSuite,
    persona_ids: List[UUID],
) -> EvaluatorSuiteResponse:
    if not persona_ids:
        return _build_suite_response(db, suite)

    existing = load_suite_combinations(db, suite.id, suite.organization_id, suite.workspace_id)
    current_persona_ids = _suite_persona_ids(existing, suite.persona_id)
    new_persona_ids = [pid for pid in persona_ids if pid not in current_persona_ids]
    if not new_persona_ids:
        return _build_suite_response(db, suite)

    agent = db.query(Agent).filter(Agent.id == suite.agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    _validate_personas_for_agent(
        db, agent, new_persona_ids, suite.organization_id, suite.workspace_id
    )

    scenario_ids = _suite_scenario_ids(existing)
    if not scenario_ids:
        raise HTTPException(status_code=400, detail="Suite has no scenarios")

    _create_child_evaluators(db, suite, new_persona_ids, scenario_ids, suite.metric_ids)
    db.commit()
    db.refresh(suite)
    return _build_suite_response(db, suite)


def replace_personas_in_suite(
    db: Session,
    suite: EvaluatorSuite,
    persona_ids: List[UUID],
) -> EvaluatorSuiteResponse:
    persona_ids = list(dict.fromkeys(persona_ids))
    if not persona_ids:
        raise HTTPException(status_code=400, detail="At least one persona is required")

    agent = db.query(Agent).filter(Agent.id == suite.agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    _validate_personas_for_agent(
        db, agent, persona_ids, suite.organization_id, suite.workspace_id
    )

    existing = load_suite_combinations(db, suite.id, suite.organization_id, suite.workspace_id)
    scenario_ids = _suite_scenario_ids(existing)
    if not scenario_ids:
        raise HTTPException(status_code=400, detail="Suite has no scenarios")

    combinations = _sync_suite_grid(db, suite, persona_ids, scenario_ids)
    db.commit()
    db.refresh(suite)
    return _build_suite_response(db, suite, combinations)


def remove_persona_from_suite(
    db: Session,
    suite: EvaluatorSuite,
    persona_id: UUID,
) -> EvaluatorSuiteResponse:
    existing = load_suite_combinations(db, suite.id, suite.organization_id, suite.workspace_id)
    current_persona_ids = _suite_persona_ids(existing, suite.persona_id)
    if persona_id not in current_persona_ids:
        raise HTTPException(status_code=404, detail="Persona not found in suite")

    if len(current_persona_ids) <= 1:
        raise HTTPException(status_code=400, detail="Cannot remove the last persona from a suite")

    combos = (
        db.query(Evaluator)
        .filter(
            Evaluator.suite_id == suite.id,
            Evaluator.persona_id == persona_id,
        )
        .all()
    )
    _delete_combination_rows(db, combos)

    remaining = load_suite_combinations(db, suite.id, suite.organization_id, suite.workspace_id)
    remaining_persona_ids = _suite_persona_ids(remaining, suite.persona_id)
    if remaining_persona_ids:
        if suite.persona_id not in remaining_persona_ids:
            suite.persona_id = remaining_persona_ids[0]

    db.commit()
    db.refresh(suite)
    return _build_suite_response(db, suite)


def delete_evaluator_suite(db: Session, suite: EvaluatorSuite) -> None:
    was_active = bool(getattr(suite, "is_active", False))
    agent_id = suite.agent_id
    workspace_id = suite.workspace_id
    combinations = load_suite_combinations(db, suite.id, suite.organization_id, suite.workspace_id)
    for combo in combinations:
        db.query(EvaluatorResult).filter(EvaluatorResult.evaluator_id == combo.id).update(
            {EvaluatorResult.evaluator_id: None}, synchronize_session=False
        )
    db.delete(suite)
    db.commit()

    if was_active:
        replacement = (
            db.query(EvaluatorSuite)
            .filter(
                EvaluatorSuite.workspace_id == workspace_id,
                EvaluatorSuite.agent_id == agent_id,
            )
            .order_by(EvaluatorSuite.created_at.desc())
            .first()
        )
        if replacement:
            replacement.is_active = True
            db.commit()


def activate_evaluator_suite(
    db: Session,
    suite: EvaluatorSuite,
) -> EvaluatorSuiteResponse:
    """Mark this suite as the active inbound configuration for its agent."""
    db.query(EvaluatorSuite).filter(
        EvaluatorSuite.workspace_id == suite.workspace_id,
        EvaluatorSuite.agent_id == suite.agent_id,
        EvaluatorSuite.id != suite.id,
    ).update({EvaluatorSuite.is_active: False}, synchronize_session=False)
    suite.is_active = True
    db.commit()
    db.refresh(suite)
    return _build_suite_response(db, suite)


def pick_round_robin_combination(
    db: Session,
    suite: EvaluatorSuite,
) -> Tuple[Evaluator, int, int]:
    combinations = load_suite_combinations(db, suite.id, suite.organization_id, suite.workspace_id)
    if not combinations:
        raise HTTPException(status_code=400, detail="Suite has no scenario combinations")

    n = len(combinations)
    idx = (suite.round_robin_index or 0) % n
    selected = combinations[idx]
    next_index = (idx + 1) % n
    suite.round_robin_index = (suite.round_robin_index or 0) + 1
    db.commit()
    db.refresh(suite)
    return selected, idx, next_index


def generate_unique_result_id(db: Session) -> str:
    max_attempts = 100
    for _ in range(max_attempts):
        candidate_id = f"{random.randint(100000, 999999)}"
        existing = db.query(EvaluatorResult).filter(EvaluatorResult.result_id == candidate_id).first()
        if not existing:
            return candidate_id
    raise HTTPException(status_code=500, detail="Failed to generate unique result ID")
