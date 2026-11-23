"""Red team runs (EFF-36): launch, monitor, stop and export adversarial tests of an agent."""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import dependencies as app_dependencies
from app.core.auth import Principal, get_principal
from app.dependencies import get_db, get_organization_id, get_workspace_id
from app.models.database import Agent, EvaluatorResult, RedTeamAttack, RedTeamRun
from app.models.enums import RedTeamRunStatus
from app.models.red_team_schemas import (
    RedTeamAttackDetailResponse,
    RedTeamAttackResponse,
    RedTeamEntitlementsResponse,
    RedTeamLaunchResponse,
    RedTeamRunCreate,
    RedTeamRunDetailResponse,
    RedTeamRunResponse,
)
from app.services.red_team.catalog import CATALOG_VERSION, catalog_payload
from app.services.red_team.presets import (
    INTENSITIES,
    MAX_FAMILY_QUOTA,
    PresetError,
    preview,
    resolve_config,
)
from app.services.red_team.report import (
    is_redacted,
    redacted_transcript,
    report_csv,
    technique_name,
)

router = APIRouter(prefix="/red-team-runs", tags=["red-team"])

CUSTOM_FEATURE = "red_team_custom"


def _custom_allowed(organization_id: UUID) -> bool:
    return bool(app_dependencies.is_feature_enabled(CUSTOM_FEATURE, organization_id))


def _generate_unique_run_id(db: Session) -> str:
    for _ in range(100):
        candidate = f"{random.randint(100000, 999999)}"
        if not db.query(RedTeamRun.id).filter(RedTeamRun.run_id == candidate).first():
            return candidate
    raise HTTPException(status_code=500, detail="Failed to generate unique run ID")


def _get_run(db: Session, run_ref: str, organization_id: UUID, workspace_id: UUID) -> RedTeamRun:
    query = db.query(RedTeamRun).filter(
        RedTeamRun.organization_id == organization_id,
        RedTeamRun.workspace_id == workspace_id,
    )
    try:
        run = query.filter(RedTeamRun.id == UUID(run_ref)).first()
    except ValueError:
        run = query.filter(RedTeamRun.run_id == run_ref).first()
    if not run:
        raise HTTPException(status_code=404, detail="Red team run not found")
    return run


def _attack_response(attack: RedTeamAttack) -> RedTeamAttackResponse:
    response = RedTeamAttackResponse.model_validate(attack)
    response.technique_name = technique_name(attack.technique_id)
    judge = attack.judge if isinstance(attack.judge, dict) else {}
    response.rationale = judge.get("rationale")
    return response


def _attacks(db: Session, run: RedTeamRun) -> list[RedTeamAttack]:
    return (
        db.query(RedTeamAttack)
        .filter(RedTeamAttack.red_team_run_id == run.id)
        .order_by(RedTeamAttack.sequence)
        .all()
    )


# --- entitlements -----------------------------------------------------------


@router.get("/entitlements", response_model=RedTeamEntitlementsResponse)
def get_red_team_entitlements(organization_id: UUID = Depends(get_organization_id)):
    custom = _custom_allowed(organization_id)
    presets = {
        name: resolve_config(name, modality="chat") | {"attack_quotas_voice": resolve_config(name, modality="voice")["attack_quotas"]}
        for name in ("quick", "standard", "thorough")
    }
    return RedTeamEntitlementsResponse(
        intensities=[i for i in INTENSITIES if i != "custom" or custom],
        custom_allowed=custom,
        max_family_quota=MAX_FAMILY_QUOTA,
        presets=presets,
        catalog=catalog_payload(),
    )


# --- launch -----------------------------------------------------------------


@router.post("", response_model=RedTeamLaunchResponse)
def launch_red_team_run(
    payload: RedTeamRunCreate,
    response: Response,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """``confirmed=false`` returns a preview and starts nothing; ``confirmed=true`` queues the run."""
    from app.services.red_team.llm import describe_run_llms, resolve_run_llms
    from app.services.red_team.orchestrator import determine_modality
    from app.services.red_team.voice import pick_persona

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

    if payload.intensity == "custom" and not _custom_allowed(organization_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "enterprise_feature_required",
                "feature": CUSTOM_FEATURE,
                "message": "Custom red team intensity is an EfficientAI Enterprise feature.",
            },
        )

    try:
        modality = determine_modality(db, agent)
        config = resolve_config(payload.intensity, modality=modality, attack_quotas=payload.attack_quotas)
        llms = resolve_run_llms(
            db,
            agent=agent,
            attacker_provider=payload.attacker_llm_provider,
            attacker_model=payload.attacker_llm_model,
            judge_provider=payload.judge_llm_provider,
            judge_model=payload.judge_llm_model,
        )
    except (PresetError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    persona_id = payload.persona_id
    if modality == "voice":
        persona = pick_persona(db, agent, payload.persona_id)
        if persona is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "No voice persona matches this agent's voice bundle TTS provider. Create one "
                    "(or pick one) so the attacker can speak."
                ),
            )
        persona_id = persona.id

    launch_preview = preview(config, modality=modality)
    if not payload.confirmed:
        return RedTeamLaunchResponse(needs_confirmation=True, modality=modality, config=config, preview=launch_preview)

    run = RedTeamRun(
        run_id=_generate_unique_run_id(db),
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent.id,
        name=payload.name,
        intensity=payload.intensity,
        modality=modality,
        config=config,
        attacker_knowledge=[item.model_dump() for item in payload.attacker_knowledge] or None,
        connection_overrides=(
            payload.connection_overrides.model_dump(exclude_none=True) if payload.connection_overrides else None
        )
        or None,
        persona_id=persona_id,
        attacker_llm_provider=payload.attacker_llm_provider,
        attacker_llm_model=payload.attacker_llm_model,
        judge_llm_provider=payload.judge_llm_provider,
        judge_llm_model=payload.judge_llm_model,
        resolved_llms=describe_run_llms(llms),
        catalog_version=CATALOG_VERSION,
        status=RedTeamRunStatus.QUEUED.value,
        max_attacks=config["max_attacks"],
        created_by=getattr(principal, "user_id", None) and str(principal.user_id),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    from app.workers.celery_app import run_red_team_task

    task = run_red_team_task.delay(str(run.id))
    run.celery_task_id = task.id
    db.commit()
    response.status_code = status.HTTP_201_CREATED
    return RedTeamLaunchResponse(
        needs_confirmation=False,
        modality=modality,
        config=config,
        preview=launch_preview,
        run=RedTeamRunResponse.model_validate(run),
    )


# --- read -------------------------------------------------------------------


@router.get("", response_model=List[RedTeamRunResponse])
def list_red_team_runs(
    agent_id: Optional[UUID] = None,
    limit: int = Query(50, ge=1, le=200),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    query = db.query(RedTeamRun).filter(
        RedTeamRun.organization_id == organization_id,
        RedTeamRun.workspace_id == workspace_id,
    )
    if agent_id:
        query = query.filter(RedTeamRun.agent_id == agent_id)
    return query.order_by(RedTeamRun.created_at.desc()).limit(limit).all()


@router.get("/{run_ref}", response_model=RedTeamRunDetailResponse)
def get_red_team_run(
    run_ref: str,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    run = _get_run(db, run_ref, organization_id, workspace_id)
    response = RedTeamRunDetailResponse.model_validate(run)
    response.attacks = [_attack_response(a) for a in _attacks(db, run)]
    return response


@router.get("/{run_ref}/attacks/{attack_id}", response_model=RedTeamAttackDetailResponse)
def get_red_team_attack(
    run_ref: str,
    attack_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    run = _get_run(db, run_ref, organization_id, workspace_id)
    attack = (
        db.query(RedTeamAttack)
        .filter(RedTeamAttack.id == attack_id, RedTeamAttack.red_team_run_id == run.id)
        .first()
    )
    if not attack:
        raise HTTPException(status_code=404, detail="Attack not found")
    base = _attack_response(attack).model_dump()
    detail = RedTeamAttackDetailResponse(
        **base,
        judge=attack.judge if isinstance(attack.judge, dict) else None,
        transcript=redacted_transcript(attack),
        evaluator_result_id=attack.evaluator_result_id,
        redacted=is_redacted(attack),
    )
    if attack.evaluator_result_id:
        result = db.query(EvaluatorResult).filter(EvaluatorResult.id == attack.evaluator_result_id).first()
        if result is not None:
            detail.evaluator_result_ref = result.result_id
            detail.has_recording = bool(result.audio_s3_key)
    return detail


# --- control ----------------------------------------------------------------


@router.post("/{run_ref}/stop", response_model=RedTeamRunResponse)
def stop_red_team_run(
    run_ref: str,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    run = _get_run(db, run_ref, organization_id, workspace_id)
    if run.status in RedTeamRunStatus.terminal():
        raise HTTPException(status_code=409, detail=f"Run is already {run.status}")
    run.cancel_requested = True
    if run.status == RedTeamRunStatus.QUEUED.value:
        # Not picked up yet: the orchestrator's queued-only guard makes the task a no-op.
        from app.services.red_team.report import build_report

        run.status = RedTeamRunStatus.CANCELLED.value
        run.report = build_report(run, [])
        run.verdict = run.report["verdict"]
        run.finished_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(run)
    return run


@router.delete("/{run_ref}", status_code=status.HTTP_204_NO_CONTENT)
def delete_red_team_run(
    run_ref: str,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    run = _get_run(db, run_ref, organization_id, workspace_id)
    if run.status not in RedTeamRunStatus.terminal():
        raise HTTPException(status_code=409, detail="Stop the run before deleting it")
    db.query(RedTeamAttack).filter(RedTeamAttack.red_team_run_id == run.id).delete(synchronize_session=False)
    db.delete(run)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- exports ----------------------------------------------------------------


def _terminal_run(db: Session, run_ref: str, organization_id: UUID, workspace_id: UUID) -> RedTeamRun:
    run = _get_run(db, run_ref, organization_id, workspace_id)
    if run.status not in RedTeamRunStatus.terminal():
        raise HTTPException(status_code=409, detail="Wait for the run to finish first")
    return run


@router.get("/{run_ref}/report.csv")
def download_red_team_csv(
    run_ref: str,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    run = _terminal_run(db, run_ref, organization_id, workspace_id)
    body = report_csv(run, _attacks(db, run))
    return Response(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="red-team-{run.run_id}.csv"'},
    )


@router.get("/{run_ref}/report.pdf")
def download_red_team_pdf(
    run_ref: str,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    from app.services.red_team.pdf_report import render_red_team_pdf

    run = _terminal_run(db, run_ref, organization_id, workspace_id)
    agent = db.query(Agent).filter(Agent.id == run.agent_id).first()
    try:
        pdf_bytes = render_red_team_pdf(run=run, agent=agent, attacks=_attacks(db, run))
    except RuntimeError as exc:
        return JSONResponse(status_code=503, content={"detail": str(exc)})
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="red-team-{run.run_id}-report.pdf"'},
    )
