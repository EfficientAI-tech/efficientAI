"""Start simulation runs and evaluation-suite runs; request failure analysis.

These cost money (LLM and voice minutes on the org's providers), so the card
shows how many calls will run before the user confirms. Undo cancels a run
that hasn't finished.
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from fastapi import BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.auth.capabilities import SIM_MANAGE
from app.models.database import Evaluator, EvaluatorSuite
from app.services.copilot.actions.base import (
    ActionContext,
    ActionKind,
    ActionResult,
    EntityRef,
    register_kind,
)
from app.services.copilot.actions.kinds._common import agent_or_error, principal_for

MAX_TRIALS_PER_RUN = 500


class SimulationRunFields(BaseModel):
    agent_id: UUID
    scenario_ids: list[UUID] = Field(..., min_length=1, max_length=50)
    persona_ids: list[UUID] = Field(..., min_length=1, max_length=20)
    metric_ids: Optional[list[UUID]] = Field(None, description="Omit to use the agent's enabled metrics.")
    n_attempts: int = Field(1, ge=1, le=10, description="How many times to run each scenario × persona.")
    pass_threshold: float = Field(0.7, ge=0, le=1)
    name: Optional[str] = Field(None, max_length=255)

    def trials(self) -> int:
        return len(self.scenario_ids) * len(self.persona_ids) * self.n_attempts


def _estimate_run(_db: Session, _org: UUID, _ws: UUID, p: SimulationRunFields) -> dict[str, Any]:
    return {
        "simulated_calls": p.trials(),
        "note": "Each call uses the agent's production and test LLMs on your providers.",
    }


def _start_run(ctx: ActionContext, p: SimulationRunFields) -> ActionResult:
    from app.api.v1.routes.simulation_runs import create_simulation_run
    from app.models.schemas import SimulationRunCreate

    if p.trials() > MAX_TRIALS_PER_RUN:
        raise ValueError(f"That's {p.trials()} calls; the assistant can start at most {MAX_TRIALS_PER_RUN} at once.")
    agent_or_error(ctx.db, ctx.organization_id, ctx.workspace_id, p.agent_id)
    run = create_simulation_run(
        payload=SimulationRunCreate(
            agent_id=p.agent_id,
            name=p.name,
            scenario_ids=p.scenario_ids,
            persona_ids=p.persona_ids,
            metric_ids=p.metric_ids,
            n_attempts=p.n_attempts,
            pass_threshold=p.pass_threshold,
        ),
        organization_id=ctx.organization_id,
        workspace_id=ctx.workspace_id,
        db=ctx.db,
        principal=principal_for(ctx),
    )
    return ActionResult(
        summary=f"Started simulation run {run.run_id} ({run.expected_trials} calls).",
        created=[EntityRef("simulation run", run.run_id, run.name or f"Run {run.run_id}", f"/simulations/{run.run_id}")],
        undo_state={"run_ref": run.run_id},
        data={"run_id": run.run_id, "status": getattr(run.status, "value", run.status)},
    )


def _cancel_run(ctx: ActionContext, state: dict[str, Any]) -> None:
    from app.api.v1.routes.simulation_runs import cancel_simulation_run

    cancel_simulation_run(
        run_ref=state["run_ref"],
        organization_id=ctx.organization_id,
        workspace_id=ctx.workspace_id,
        db=ctx.db,
    )


register_kind(ActionKind(
    kind="start_simulation_run",
    title="Start simulation run",
    payload_model=SimulationRunFields,
    apply=_start_run,
    undo=_cancel_run,
    describe=lambda p: f"{p.trials()} simulated call(s): {len(p.scenario_ids)} scenario(s) × {len(p.persona_ids)} persona(s) × {p.n_attempts}",
    capability=SIM_MANAGE,
    costly=True,
    estimate=_estimate_run,
))


class SuiteRunFields(BaseModel):
    suite_id: UUID
    runs_per_combination: int = Field(1, ge=1, le=10)


def _suite_combinations(db: Session, org: UUID, ws: UUID, suite_id: UUID) -> int:
    return int(
        db.query(func.count(Evaluator.id))
        .filter(Evaluator.suite_id == suite_id, Evaluator.organization_id == org, Evaluator.workspace_id == ws)
        .scalar()
        or 0
    )


def _estimate_suite(db: Session, org: UUID, ws: UUID, p: SuiteRunFields) -> dict[str, Any]:
    combos = _suite_combinations(db, org, ws, p.suite_id)
    return {"test_calls": combos * p.runs_per_combination, "combinations": combos}


async def _run_suite(ctx: ActionContext, p: SuiteRunFields) -> ActionResult:
    from app.api.v1.routes.evaluator_suites import run_suite
    from app.models.schemas import RunEvaluatorSuiteRequest

    suite = ctx.db.query(EvaluatorSuite).filter(
        EvaluatorSuite.id == p.suite_id,
        EvaluatorSuite.organization_id == ctx.organization_id,
        EvaluatorSuite.workspace_id == ctx.workspace_id,
    ).first()
    if suite is None:
        raise ValueError("That evaluation suite isn't in this workspace.")
    tasks = BackgroundTasks()
    response = run_suite(
        suite_id=p.suite_id,
        request=RunEvaluatorSuiteRequest(runs_per_combination=p.runs_per_combination),
        background_tasks=tasks,
        organization_id=ctx.organization_id,
        workspace_id=ctx.workspace_id,
        db=ctx.db,
    )
    await tasks()  # usage billing the route defers to after the response
    total = getattr(response, "total_runs", None) or (response or {}).get("total_runs", 0)
    return ActionResult(
        summary=f"Started {total} test call(s) for suite '{suite.name}'. Results appear under Results.",
        data={"total_runs": total},
        created=[EntityRef("suite run", str(suite.id), suite.name, f"/evaluate-test-agents/{suite.id}")],
    )


register_kind(ActionKind(
    kind="run_evaluator_suite",
    title="Run evaluation suite",
    payload_model=SuiteRunFields,
    apply=_run_suite,
    describe=lambda p: f"Run every combination of a suite {p.runs_per_combination} time(s)",
    capability=SIM_MANAGE,
    costly=True,
    estimate=_estimate_suite,
))


class FailureAnalysisFields(BaseModel):
    run_ref: str = Field(..., max_length=64, description="Simulation run id (6-digit) or UUID.")


def _analyse(ctx: ActionContext, p: FailureAnalysisFields) -> ActionResult:
    from app.api.v1.routes.simulation_runs import generate_simulation_failure_analysis

    generate_simulation_failure_analysis(
        run_ref=p.run_ref,
        body=None,
        organization_id=ctx.organization_id,
        workspace_id=ctx.workspace_id,
        db=ctx.db,
    )
    return ActionResult(
        summary=f"Started failure analysis for run {p.run_ref}. It takes a few minutes; ask me for the results after.",
        data={"run_ref": p.run_ref},
    )


register_kind(ActionKind(
    kind="analyse_simulation_failures",
    title="Analyse simulation failures",
    payload_model=FailureAnalysisFields,
    apply=_analyse,
    describe=lambda p: f"Cluster the failed calls of run {p.run_ref} and suggest prompt fixes (uses your LLM)",
    capability=SIM_MANAGE,
    costly=True,
    editable=False,
))
