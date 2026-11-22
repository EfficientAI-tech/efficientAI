"""Read tools for simulation runs and evaluation suites."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.auth.capabilities import SIM_VIEW
from app.models.database import Evaluator, EvaluatorSuite, SimulationRun
from app.services.copilot.registry import CopilotTool, ToolContext, ToolError, register
from app.services.copilot.tools.workspace import _clip, _iso, _resolve_agent

GROUP = "simulations"


class RunListArgs(BaseModel):
    agent: Optional[str] = Field(None, max_length=64, description="Only this agent's runs.")
    limit: int = Field(10, ge=1, le=25)


def _list_runs(ctx: ToolContext, db: Session, args: RunListArgs) -> dict:
    q = db.query(SimulationRun).filter(
        SimulationRun.organization_id == ctx.organization_id,
        SimulationRun.workspace_id == ctx.workspace_id,
    )
    if args.agent:
        q = q.filter(SimulationRun.agent_id == _resolve_agent(db, ctx, args.agent).id)
    rows = q.order_by(SimulationRun.created_at.desc()).limit(args.limit).all()
    return {
        "runs": [
            {
                "run_id": r.run_id,
                "name": r.name,
                "status": r.status,
                "pass_rate": (r.summary or {}).get("pass_rate"),
                "trials": r.expected_trials,
                "created_at": _iso(r.created_at),
                "link": f"/simulations/{r.run_id}",
            }
            for r in rows
        ]
    }


class RunRef(BaseModel):
    run: str = Field(..., max_length=64, description="Simulation run id (6-digit) or UUID.")


def _call(fn, **kwargs) -> Any:
    try:
        return fn(**kwargs)
    except HTTPException as exc:
        raise ToolError(str(exc.detail)) from exc


def _get_run(ctx: ToolContext, db: Session, args: RunRef) -> dict:
    from app.api.v1.routes.simulation_runs import get_simulation_failure_analysis, get_simulation_run

    scope = {"organization_id": ctx.organization_id, "workspace_id": ctx.workspace_id, "db": db}
    run = _call(get_simulation_run, run_ref=args.run, **scope)
    summary = run.summary or {}
    out: dict[str, Any] = {
        "run_id": run.run_id,
        "name": run.name,
        "status": run.status,
        "progress": {"expected": run.expected_trials, "completed": run.completed_trials, "failed": run.failed_trials},
        "pass_rate": summary.get("pass_rate"),
        "pass_threshold": run.pass_threshold,
        "uses_success_criteria": summary.get("uses_success_criteria"),
        "weakest_metrics": [
            {k: m.get(k) for k in ("metric_id", "name", "mean", "pass_rate", "n")}
            for m in (summary.get("metrics") or [])[:8]
        ],
        "failing_combinations": [
            {k: c.get(k) for k in ("scenario_name", "persona_name", "attempts", "passed", "mean_reward")}
            for c in (summary.get("combos") or [])
            if (c.get("passed") or 0) < (c.get("attempts") or 0)
        ][:8],
        "error": _clip(run.error_message, 300),
        "link": f"/simulations/{run.run_id}",
    }
    if run.status in ("completed", "failed", "cancelled"):
        analysis = _call(get_simulation_failure_analysis, run_ref=args.run, **scope)
        clusters = analysis.metric_clusters
        out["failure_analysis"] = {
            "failed_trials": analysis.failed_trials,
            "status": getattr(clusters, "status", "not_generated") if clusters else "not_generated",
            "clusters": [
                {"metric": g.metric_name, "label": c.label, "trials": c.count, "why": _clip(c.failure_reason or c.observation, 250)}
                for g in ((clusters.groups or []) if clusters else [])[:6]
                for c in (g.clusters or [])[:3]
            ],
            "prompt_suggestions": len((analysis.prompt_improvements.suggestions or []) if analysis.prompt_improvements else []),
        }
    return out


class SuiteListArgs(BaseModel):
    agent: Optional[str] = Field(None, max_length=64)
    limit: int = Field(10, ge=1, le=25)


def _list_suites(ctx: ToolContext, db: Session, args: SuiteListArgs) -> dict:
    q = db.query(EvaluatorSuite).filter(
        EvaluatorSuite.organization_id == ctx.organization_id,
        EvaluatorSuite.workspace_id == ctx.workspace_id,
    )
    if args.agent:
        q = q.filter(EvaluatorSuite.agent_id == _resolve_agent(db, ctx, args.agent).id)
    suites = q.order_by(EvaluatorSuite.updated_at.desc()).limit(args.limit).all()
    counts = dict(
        db.query(Evaluator.suite_id, func.count(Evaluator.id))
        .filter(Evaluator.suite_id.in_([s.id for s in suites]))
        .group_by(Evaluator.suite_id)
        .all()
    ) if suites else {}
    return {
        "suites": [
            {
                "id": str(s.id),
                "name": s.name,
                "agent_id": str(s.agent_id),
                "combinations": int(counts.get(s.id, 0)),
                "is_active": bool(getattr(s, "is_active", False)),
                "link": f"/evaluate-test-agents/{s.id}",
            }
            for s in suites
        ]
    }


for tool in (
    CopilotTool(
        name="list_simulation_runs",
        description="Recent simulation runs (batches of simulated test calls) with status and pass rate.",
        args_model=RunListArgs, handler=_list_runs, capability=SIM_VIEW, group=GROUP,
    ),
    CopilotTool(
        name="get_simulation_run",
        description="One simulation run: progress, pass rate, weakest metrics, failing scenario × persona combinations and failure analysis.",
        args_model=RunRef, handler=_get_run, capability=SIM_VIEW, group=GROUP,
    ),
    CopilotTool(
        name="list_evaluation_suites",
        description="Evaluation suites (an agent's persona × scenario test grid) in this workspace.",
        args_model=SuiteListArgs, handler=_list_suites, capability=SIM_VIEW, group=GROUP,
    ),
):
    register(tool)
