"""Evaluator suite API routes."""

from typing import List
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_organization_id, get_workspace_id
from app.models.database import Agent, EvaluatorSuite, Scenario
from app.models.schemas import (
    EvaluatorSuiteAddScenariosRequest,
    EvaluatorSuiteCreate,
    EvaluatorSuiteResponse,
    EvaluatorSuiteUpdate,
    RunEvaluatorSuiteRequest,
    RunEvaluatorSuiteResponse,
    RunNextCombinationRequest,
    RunNextCombinationResponse,
    ChooseNextCombinationResponse,
)
from app.services.billing.flexprice_service import record_evaluator_run_requested
from app.services.evaluators.evaluator_helpers import expand_suite_runs, load_suite_combinations
from app.services.evaluators.evaluator_phone_run_service import (
    initiate_phone_evaluator_call,
    run_phone_evaluator_batch,
)
from app.services.evaluators.evaluator_run_service import queue_evaluator_runs
from app.services.evaluators.evaluator_suite_service import (
    activate_evaluator_suite,
    add_scenarios_to_suite,
    create_evaluator_suite,
    delete_evaluator_suite,
    get_suite_or_404,
    pick_round_robin_combination,
    remove_scenario_from_suite,
    update_evaluator_suite,
    _build_suite_response,
)

router = APIRouter(prefix="/evaluator-suites", tags=["evaluator-suites"])


def _resolve_run_strategy(agent: Agent) -> str:
    call_medium = agent.call_medium or "phone_call"
    call_type = agent.call_type or "outbound"
    if call_medium == "web_call":
        return "web_bridge"
    if call_medium == "phone_call":
        if call_type == "inbound":
            return "phone_inbound"
        return "phone_outbound"
    return "unsupported"


@router.post("", response_model=EvaluatorSuiteResponse, status_code=201)
def create_suite(
    data: EvaluatorSuiteCreate,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    return create_evaluator_suite(db, organization_id, workspace_id, data)


@router.get("", response_model=List[EvaluatorSuiteResponse])
def list_suites(
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    suites = (
        db.query(EvaluatorSuite)
        .filter(
            EvaluatorSuite.organization_id == organization_id,
            EvaluatorSuite.workspace_id == workspace_id,
        )
        .order_by(EvaluatorSuite.agent_id, EvaluatorSuite.is_active.desc(), EvaluatorSuite.created_at.desc())
        .all()
    )
    return [_build_suite_response(db, suite) for suite in suites]


@router.get("/{suite_id}", response_model=EvaluatorSuiteResponse)
def get_suite(
    suite_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    suite = get_suite_or_404(db, suite_id, organization_id, workspace_id)
    return _build_suite_response(db, suite)


@router.put("/{suite_id}", response_model=EvaluatorSuiteResponse)
def update_suite(
    suite_id: UUID,
    data: EvaluatorSuiteUpdate,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    suite = get_suite_or_404(db, suite_id, organization_id, workspace_id)
    return update_evaluator_suite(db, suite, data)


@router.post("/{suite_id}/scenarios", response_model=EvaluatorSuiteResponse)
def add_scenarios(
    suite_id: UUID,
    data: EvaluatorSuiteAddScenariosRequest,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    suite = get_suite_or_404(db, suite_id, organization_id, workspace_id)
    return add_scenarios_to_suite(db, suite, data.scenario_ids)


@router.delete("/{suite_id}/scenarios/{scenario_id}", response_model=EvaluatorSuiteResponse)
def remove_scenario(
    suite_id: UUID,
    scenario_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    suite = get_suite_or_404(db, suite_id, organization_id, workspace_id)
    return remove_scenario_from_suite(db, suite, scenario_id)


@router.post("/{suite_id}/activate", response_model=EvaluatorSuiteResponse)
def activate_suite(
    suite_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Set this suite as the active inbound configuration for its agent."""
    suite = get_suite_or_404(db, suite_id, organization_id, workspace_id)
    return activate_evaluator_suite(db, suite)


@router.delete("/{suite_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_suite(
    suite_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    suite = get_suite_or_404(db, suite_id, organization_id, workspace_id)
    delete_evaluator_suite(db, suite)
    return Response(status_code=204)


@router.post("/{suite_id}/run", response_model=RunEvaluatorSuiteResponse)
def run_suite(
    suite_id: UUID,
    request: RunEvaluatorSuiteRequest,
    background_tasks: BackgroundTasks,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    suite = get_suite_or_404(db, suite_id, organization_id, workspace_id)
    agent = db.query(Agent).filter(Agent.id == suite.agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    combinations = load_suite_combinations(db, suite.id, organization_id, workspace_id)
    if not combinations:
        raise HTTPException(status_code=400, detail="Suite has no scenario combinations")

    combination_ids = [c.id for c in combinations]
    expanded = expand_suite_runs(combination_ids, request.runs_per_combination)
    strategy = _resolve_run_strategy(agent)

    task_ids: List[str] = []
    evaluator_results = []
    phone_call_refs: List[str] = []

    if strategy == "web_bridge":
        task_ids, evaluator_results = queue_evaluator_runs(
            db, organization_id, workspace_id, expanded
        )
    elif strategy == "phone_outbound":
        if not request.to_number:
            raise HTTPException(status_code=400, detail="to_number is required for phone outbound runs")
        evaluators_by_id = {c.id: c for c in combinations}
        ordered_evaluators = [evaluators_by_id[eid] for eid in expanded if eid in evaluators_by_id]
        phone_call_refs, evaluator_results = run_phone_evaluator_batch(
            db,
            organization_id,
            workspace_id,
            agent,
            ordered_evaluators,
            request.to_number,
            from_number=request.from_number,
        )
    elif strategy == "phone_inbound":
        raise HTTPException(
            status_code=400,
            detail="Inbound agents use POST /evaluator-suites/{id}/run-next for round-robin test calls",
        )
    else:
        raise HTTPException(status_code=400, detail="Unsupported agent call configuration for automated runs")

    total_runs = len(expanded)
    if task_ids:
        background_tasks.add_task(
            record_evaluator_run_requested,
            organization_id,
            uuid4(),
            workspace_id=workspace_id,
            quantity=len(task_ids),
        )

    return RunEvaluatorSuiteResponse(
        total_runs=total_runs,
        task_ids=task_ids,
        evaluator_results=evaluator_results,
        phone_call_refs=phone_call_refs,
    )


@router.post("/{suite_id}/choose-next", response_model=ChooseNextCombinationResponse)
def choose_next_combination(
    suite_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Advance inbound round-robin to the next scenario without placing a call."""
    suite = get_suite_or_404(db, suite_id, organization_id, workspace_id)
    agent = db.query(Agent).filter(Agent.id == suite.agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if (agent.call_type or "outbound").lower() != "inbound":
        raise HTTPException(
            status_code=400,
            detail="choose-next is only for inbound agent suites",
        )

    if not suite.is_active:
        raise HTTPException(
            status_code=400,
            detail="Only the active suite for this agent can advance inbound rotation. Activate this suite first.",
        )

    selected, idx, next_index = pick_round_robin_combination(db, suite)
    scenario = db.query(Scenario).filter(Scenario.id == selected.scenario_id).first()
    scenario_name = scenario.name if scenario else "Unknown Scenario"

    return ChooseNextCombinationResponse(
        evaluator_id=selected.id,
        scenario_id=selected.scenario_id,
        scenario_name=scenario_name,
        combination_index=idx,
        next_index=next_index,
    )


@router.post("/{suite_id}/run-next", response_model=RunNextCombinationResponse)
def run_next_combination(
    suite_id: UUID,
    request: RunNextCombinationRequest,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    suite = get_suite_or_404(db, suite_id, organization_id, workspace_id)
    agent = db.query(Agent).filter(Agent.id == suite.agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if (agent.call_type or "outbound").lower() == "inbound":
        raise HTTPException(
            status_code=400,
            detail="Inbound suites use POST /evaluator-suites/{id}/choose-next to advance rotation without placing a call",
        )

    if not agent.phone_number:
        raise HTTPException(status_code=400, detail="Agent has no inbound phone number configured")

    selected, idx, next_index = pick_round_robin_combination(db, suite)
    scenario = db.query(Scenario).filter(Scenario.id == selected.scenario_id).first()
    scenario_name = scenario.name if scenario else "Unknown Scenario"

    strategy = _resolve_run_strategy(agent)
    task_id = None
    result_response = None
    phone_call_ref = None
    call_short_id = None

    if strategy == "web_bridge":
        task_ids, results = queue_evaluator_runs(
            db, organization_id, workspace_id, [selected.id]
        )
        task_id = task_ids[0] if task_ids else None
        result_response = results[0] if results else None
    elif strategy in ("phone_outbound", "phone_inbound"):
        to_number = agent.phone_number
        phone_call_ref, call_short_id, result_response = initiate_phone_evaluator_call(
            db,
            organization_id,
            workspace_id,
            selected,
            agent,
            to_number,
            from_number=request.from_number,
        )
    else:
        raise HTTPException(status_code=400, detail="Unsupported agent call configuration")

    return RunNextCombinationResponse(
        evaluator_id=selected.id,
        scenario_id=selected.scenario_id,
        scenario_name=scenario_name,
        combination_index=idx,
        next_index=next_index,
        evaluator_result_id=result_response.id if result_response else None,
        result_id=result_response.result_id if result_response else None,
        task_id=task_id,
        phone_call_ref=phone_call_ref,
        call_short_id=call_short_id,
    )


from app.core.auth.capabilities import SIM_MANAGE, SIM_VIEW
from app.core.auth.workspace_route_capabilities import apply_workspace_route_capabilities

apply_workspace_route_capabilities(
    router,
    view_capability=SIM_VIEW,
    manage_capability=SIM_MANAGE,
)
