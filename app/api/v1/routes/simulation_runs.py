"""Harbor simulation runs: launch, monitor and inspect test ↔ production agent runs."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.core.api_rate_limit import enforce_resource_create_rate_limit
from app.core.auth import Principal
from app.dependencies import get_db, get_organization_id, get_workspace_id
from app.models.database import (
    Agent,
    EvaluatorResult,
    Persona,
    Scenario,
    SimulationRun,
    SimulationRunStatus,
)
from app.models.schemas import (
    SimulationRunCreate,
    SimulationRunResponse,
    SimulationTrialDetailResponse,
    SimulationTrialResponse,
)
from app.services.harbor.result_ingest import (
    LOCAL_ARTIFACT_PREFIX,
    attempt_numbers,
    compute_summary,
    trial_results,
)
from app.services.harbor.success_criteria import (
    criteria_to_storage,
    validate_metric_success_criteria,
)

router = APIRouter(prefix="/simulation-runs", tags=["simulation-runs"])


def _generate_unique_run_id(db: Session) -> str:
    for _ in range(100):
        candidate = f"{random.randint(100000, 999999)}"
        if not db.query(SimulationRun).filter(SimulationRun.run_id == candidate).first():
            return candidate
    raise HTTPException(status_code=500, detail="Failed to generate unique run ID")


def _get_run(db: Session, run_ref: str, organization_id: UUID, workspace_id: UUID) -> SimulationRun:
    query = db.query(SimulationRun).filter(
        SimulationRun.organization_id == organization_id,
        SimulationRun.workspace_id == workspace_id,
    )
    try:
        run = query.filter(SimulationRun.id == UUID(run_ref)).first()
    except ValueError:
        run = query.filter(SimulationRun.run_id == run_ref).first()
    if not run:
        raise HTTPException(status_code=404, detail="Simulation run not found")
    return run


def _run_response(db: Session, run: SimulationRun) -> SimulationRunResponse:
    response = SimulationRunResponse.model_validate(run)
    response.has_artifacts = bool(run.artifacts_s3_key)
    if run.status not in SimulationRunStatus.terminal():
        # Live KPIs while trials are still landing; the stored summary is final-only.
        response.summary = compute_summary(db, run, trial_results(db, run.id))
    return response


def _validate_agent_llms(db: Session, agent: Agent, payload: SimulationRunCreate) -> None:
    from app.services.agents.chat_llm_config import resolve_simulation_llm
    from app.services.agents.chat_production_leg import uses_live_production_leg

    try:
        if not payload.test_llm_model:
            resolve_simulation_llm(
                db, agent=agent, organization_id=agent.organization_id, leg="test"
            )
        if not payload.production_llm_model and not uses_live_production_leg(agent):
            resolve_simulation_llm(
                db, agent=agent, organization_id=agent.organization_id, leg="main"
            )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _create_and_queue(
    db: Session,
    *,
    payload: SimulationRunCreate,
    organization_id: UUID,
    workspace_id: UUID,
    created_by: Optional[str],
) -> SimulationRun:
    agent = (
        db.query(Agent)
        .filter(
            Agent.id == payload.agent_id,
            Agent.organization_id == organization_id,
            Agent.workspace_id == workspace_id,
        )
        .first()
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    _validate_agent_llms(db, agent, payload)

    found_scenarios = (
        db.query(Scenario.id)
        .filter(Scenario.id.in_(payload.scenario_ids), Scenario.organization_id == organization_id)
        .count()
    )
    found_personas = (
        db.query(Persona.id)
        .filter(Persona.id.in_(payload.persona_ids), Persona.organization_id == organization_id)
        .count()
    )
    if found_scenarios != len(set(payload.scenario_ids)) or found_personas != len(
        set(payload.persona_ids)
    ):
        raise HTTPException(status_code=404, detail="One or more scenarios or personas not found")

    stored_criteria = None
    if payload.metric_success_criteria:
        try:
            validate_metric_success_criteria(
                db,
                organization_id=organization_id,
                metric_ids=payload.metric_ids or [],
                criteria=payload.metric_success_criteria,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        stored_criteria = criteria_to_storage(payload.metric_success_criteria)

    run = SimulationRun(
        run_id=_generate_unique_run_id(db),
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent.id,
        name=payload.name,
        scenario_ids=[str(s) for s in dict.fromkeys(payload.scenario_ids)],
        persona_ids=[str(p) for p in dict.fromkeys(payload.persona_ids)],
        metric_ids=[str(m) for m in payload.metric_ids] if payload.metric_ids else None,
        metric_success_criteria=stored_criteria,
        n_attempts=payload.n_attempts,
        n_concurrent=payload.n_concurrent,
        pass_threshold=payload.pass_threshold,
        production_llm_provider=payload.production_llm_provider,
        production_llm_model=payload.production_llm_model,
        test_llm_provider=payload.test_llm_provider,
        test_llm_model=payload.test_llm_model,
        status=SimulationRunStatus.QUEUED.value,
        expected_trials=len(set(payload.scenario_ids))
        * len(set(payload.persona_ids))
        * payload.n_attempts,
        created_by=created_by,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    from app.workers.celery_app import run_harbor_simulation_task

    task = run_harbor_simulation_task.delay(str(run.id))
    run.celery_task_id = task.id
    db.commit()
    return run


@router.post("", response_model=SimulationRunResponse, status_code=status.HTTP_201_CREATED)
def create_simulation_run(
    payload: SimulationRunCreate,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
    principal: Principal = Depends(enforce_resource_create_rate_limit),
):
    run = _create_and_queue(
        db,
        payload=payload,
        organization_id=organization_id,
        workspace_id=workspace_id,
        created_by=getattr(principal, "user_id", None) and str(principal.user_id),
    )
    return _run_response(db, run)


@router.get("", response_model=List[SimulationRunResponse])
def list_simulation_runs(
    agent_id: Optional[UUID] = None,
    limit: int = Query(50, ge=1, le=200),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    query = db.query(SimulationRun).filter(
        SimulationRun.organization_id == organization_id,
        SimulationRun.workspace_id == workspace_id,
    )
    if agent_id:
        query = query.filter(SimulationRun.agent_id == agent_id)
    runs = query.order_by(SimulationRun.created_at.desc()).limit(limit).all()
    # Listing uses stored counters only; live summaries are computed on the detail view.
    responses = []
    for run in runs:
        response = SimulationRunResponse.model_validate(run)
        response.has_artifacts = bool(run.artifacts_s3_key)
        responses.append(response)
    return responses


@router.get("/{run_ref}", response_model=SimulationRunResponse)
def get_simulation_run(
    run_ref: str,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    return _run_response(db, _get_run(db, run_ref, organization_id, workspace_id))


def _trial_response(
    result: EvaluatorResult,
    *,
    attempt: Optional[int],
    scenario_names: dict,
    persona_names: dict,
    model=SimulationTrialResponse,
    **extra,
):
    return model(
        id=result.id,
        result_id=result.result_id,
        harbor_trial_name=result.harbor_trial_name,
        scenario_id=result.scenario_id,
        scenario_name=scenario_names.get(result.scenario_id),
        persona_id=result.persona_id,
        persona_name=persona_names.get(result.persona_id),
        attempt_index=result.attempt_index or attempt,
        status=result.status,
        reward=result.reward,
        passed=result.passed,
        turns=len(result.speaker_segments or []),
        metric_scores=result.metric_scores,
        error_message=result.error_message,
        created_at=result.created_at,
        updated_at=result.updated_at,
        **extra,
    )


def _names(db: Session, results: list[EvaluatorResult]) -> tuple[dict, dict]:
    scenario_ids = {r.scenario_id for r in results if r.scenario_id}
    persona_ids = {r.persona_id for r in results if r.persona_id}
    scenarios = (
        db.query(Scenario.id, Scenario.name).filter(Scenario.id.in_(scenario_ids)).all()
        if scenario_ids
        else []
    )
    personas = (
        db.query(Persona.id, Persona.name).filter(Persona.id.in_(persona_ids)).all()
        if persona_ids
        else []
    )
    return dict(scenarios), dict(personas)


@router.get("/{run_ref}/trials", response_model=List[SimulationTrialResponse])
def list_simulation_trials(
    run_ref: str,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    run = _get_run(db, run_ref, organization_id, workspace_id)
    results = trial_results(db, run.id)
    attempts = attempt_numbers(results)
    scenario_names, persona_names = _names(db, results)
    return [
        _trial_response(
            r,
            attempt=attempts.get(r.id),
            scenario_names=scenario_names,
            persona_names=persona_names,
        )
        for r in results
    ]


def _load_trajectory(run: SimulationRun, result: EvaluatorResult) -> Optional[dict]:
    from app.services.harbor.job_runner import harbor_job_dir

    if not result.harbor_trial_name:
        return None
    path = harbor_job_dir(run) / result.harbor_trial_name / "agent" / "trajectory.json"
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


@router.get("/{run_ref}/trials/{trial_id}", response_model=SimulationTrialDetailResponse)
def get_simulation_trial(
    run_ref: str,
    trial_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    run = _get_run(db, run_ref, organization_id, workspace_id)
    results = trial_results(db, run.id)
    result = next((r for r in results if r.id == trial_id), None)
    if not result:
        raise HTTPException(status_code=404, detail="Trial not found")
    scenario_names, persona_names = _names(db, [result])
    call_data = result.call_data if isinstance(result.call_data, dict) else {}
    return _trial_response(
        result,
        attempt=attempt_numbers(results).get(result.id),
        scenario_names=scenario_names,
        persona_names=persona_names,
        model=SimulationTrialDetailResponse,
        speaker_segments=result.speaker_segments,
        call_analysis=call_data.get("call_analysis"),
        trajectory=_load_trajectory(run, result),
    )


@router.post("/{run_ref}/cancel", response_model=SimulationRunResponse)
def cancel_simulation_run(
    run_ref: str,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    run = _get_run(db, run_ref, organization_id, workspace_id)
    if run.status in SimulationRunStatus.terminal():
        raise HTTPException(status_code=409, detail=f"Run is already {run.status}")
    run.cancel_requested = True
    if run.status == SimulationRunStatus.QUEUED.value:
        # Not picked up yet: the task's queued-only guard makes it a no-op.
        from datetime import datetime, timezone

        run.status = SimulationRunStatus.CANCELLED.value
        run.finished_at = datetime.now(timezone.utc)
    db.commit()
    return _run_response(db, run)


@router.post(
    "/{run_ref}/rerun", response_model=SimulationRunResponse, status_code=status.HTTP_201_CREATED
)
def rerun_simulation_run(
    run_ref: str,
    only_failed: bool = False,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
    principal: Principal = Depends(enforce_resource_create_rate_limit),
):
    """Clone a run's config; ``only_failed`` keeps scenarios/personas with a failing trial."""
    run = _get_run(db, run_ref, organization_id, workspace_id)
    scenario_ids, persona_ids = list(run.scenario_ids or []), list(run.persona_ids or [])
    if only_failed:
        failing = [r for r in trial_results(db, run.id) if not r.passed]
        if not failing:
            raise HTTPException(status_code=400, detail="No failed trials to re-run")
        scenario_ids = list(dict.fromkeys(str(r.scenario_id) for r in failing))
        persona_ids = list(dict.fromkeys(str(r.persona_id) for r in failing))
    rerun_metric_ids = run.metric_ids
    rerun_criteria = None
    if run.metric_success_criteria:
        from app.models.schemas import MetricSuccessCriterion

        rerun_criteria = [
            MetricSuccessCriterion.model_validate(c) for c in run.metric_success_criteria
        ]
        rerun_metric_ids = [c.metric_id for c in rerun_criteria]
    payload = SimulationRunCreate(
        agent_id=run.agent_id,
        name=f"{run.name or f'Run {run.run_id}'} (re-run{' failed' if only_failed else ''})",
        scenario_ids=scenario_ids,
        persona_ids=persona_ids,
        metric_ids=[UUID(str(m)) for m in rerun_metric_ids] if rerun_metric_ids else None,
        metric_success_criteria=rerun_criteria,
        n_attempts=run.n_attempts,
        n_concurrent=run.n_concurrent,
        pass_threshold=run.pass_threshold,
        production_llm_provider=run.production_llm_provider,
        production_llm_model=run.production_llm_model,
        test_llm_provider=run.test_llm_provider,
        test_llm_model=run.test_llm_model,
    )
    new_run = _create_and_queue(
        db,
        payload=payload,
        organization_id=organization_id,
        workspace_id=workspace_id,
        created_by=getattr(principal, "user_id", None) and str(principal.user_id),
    )
    return _run_response(db, new_run)


@router.get("/{run_ref}/artifacts")
def download_simulation_artifacts(
    run_ref: str,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Harbor job tarball (tasks, trajectories, rewards); open locally with ``harbor view``."""
    run = _get_run(db, run_ref, organization_id, workspace_id)
    key = run.artifacts_s3_key
    if not key:
        raise HTTPException(status_code=404, detail="No artifacts for this run yet")
    filename = f"simulation-run-{run.run_id}.tar.gz"
    if key.startswith(LOCAL_ARTIFACT_PREFIX):
        path = Path(key[len(LOCAL_ARTIFACT_PREFIX) :])
        if not path.exists():
            raise HTTPException(status_code=404, detail="Artifact file no longer exists")
        return FileResponse(path, media_type="application/gzip", filename=filename)

    from app.services.storage.blob_storage_service import blob_storage_service

    return Response(
        content=blob_storage_service.download_file_by_key(key),
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
