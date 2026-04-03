"""
API routes for GEPA prompt optimization (Enterprise feature).

Allows users to trigger optimization runs for voice agents, view candidates,
accept the best prompt, and push it to the voice provider.
"""

from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from loguru import logger

from app.dependencies import get_db, get_organization_id, get_api_key, require_enterprise_feature
from app.models.database import (
    Agent,
    Evaluator,
    Integration,
    PromptOptimizationCandidate,
    PromptOptimizationRun,
    VoiceBundle,
)
from app.models.enums import PromptOptimizationStatus
from app.core.encryption import decrypt_api_key
from app.services.voice_providers import get_voice_provider


router = APIRouter(
    prefix="/prompt-optimization",
    tags=["Prompt Optimization"],
    dependencies=[Depends(require_enterprise_feature("gepa_optimization"))],
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class OptimizationRunCreate(BaseModel):
    agent_id: UUID
    evaluator_id: Optional[UUID] = None
    voice_bundle_id: Optional[UUID] = None
    config: Optional[Dict[str, Any]] = Field(
        default=None,
        description="GEPA hyperparameter overrides (max_metric_calls, minibatch_size, etc.)",
    )


class OptimizationRunResponse(BaseModel):
    id: UUID
    agent_id: UUID
    evaluator_id: Optional[UUID] = None
    voice_bundle_id: Optional[UUID] = None
    seed_prompt: str
    best_prompt: Optional[str] = None
    best_score: Optional[float] = None
    status: str
    config: Optional[Dict[str, Any]] = None
    metric_history: Optional[List[Dict[str, Any]]] = None
    num_iterations: Optional[int] = None
    num_metric_calls: Optional[int] = None
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CandidateResponse(BaseModel):
    id: UUID
    optimization_run_id: UUID
    prompt_text: str
    score: Optional[float] = None
    metric_breakdown: Optional[Dict[str, Any]] = None
    reflection_summary: Optional[str] = None
    parent_candidate_id: Optional[UUID] = None
    is_accepted: bool = False
    pushed_to_provider_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/runs", response_model=OptimizationRunResponse, status_code=201)
def create_optimization_run(
    data: OptimizationRunCreate,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Start a new GEPA prompt optimization run for an agent."""
    agent = db.query(Agent).filter(
        Agent.id == data.agent_id,
        Agent.organization_id == organization_id,
    ).first()
    if not agent:
        raise HTTPException(404, "Agent not found")

    if not agent.provider_prompt and not agent.description:
        raise HTTPException(400, "Agent has no provider prompt or description to optimize")

    evaluator = None
    if data.evaluator_id:
        evaluator = db.query(Evaluator).filter(
            Evaluator.id == data.evaluator_id,
            Evaluator.organization_id == organization_id,
        ).first()
        if not evaluator:
            raise HTTPException(404, "Evaluator not found")

    voice_bundle_id = data.voice_bundle_id or agent.voice_bundle_id
    if voice_bundle_id:
        vb = db.query(VoiceBundle).filter(VoiceBundle.id == voice_bundle_id).first()
        if not vb:
            raise HTTPException(404, "VoiceBundle not found")

    run = PromptOptimizationRun(
        organization_id=organization_id,
        agent_id=agent.id,
        evaluator_id=data.evaluator_id,
        voice_bundle_id=voice_bundle_id,
        seed_prompt=agent.provider_prompt or agent.description,
        status=PromptOptimizationStatus.PENDING.value,
        config=data.config,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    from app.workers.tasks.run_prompt_optimization import run_prompt_optimization_task

    task = run_prompt_optimization_task.delay(str(run.id))
    run.celery_task_id = task.id
    db.commit()

    logger.info(f"[GEPA] Created optimization run {run.id} for agent {agent.name}")
    return run


@router.get("/runs", response_model=List[OptimizationRunResponse])
def list_optimization_runs(
    agent_id: Optional[UUID] = None,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """List prompt optimization runs, optionally filtered by agent."""
    query = db.query(PromptOptimizationRun).filter(
        PromptOptimizationRun.organization_id == organization_id,
    )
    if agent_id:
        query = query.filter(PromptOptimizationRun.agent_id == agent_id)

    return query.order_by(PromptOptimizationRun.created_at.desc()).limit(50).all()


@router.get("/runs/{run_id}", response_model=OptimizationRunResponse)
def get_optimization_run(
    run_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Get details for a specific optimization run."""
    run = db.query(PromptOptimizationRun).filter(
        PromptOptimizationRun.id == run_id,
        PromptOptimizationRun.organization_id == organization_id,
    ).first()
    if not run:
        raise HTTPException(404, "Optimization run not found")
    return run


@router.delete("/runs/{run_id}", status_code=204)
def delete_optimization_run(
    run_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Delete an optimization run and all its candidates."""
    run = db.query(PromptOptimizationRun).filter(
        PromptOptimizationRun.id == run_id,
        PromptOptimizationRun.organization_id == organization_id,
    ).first()
    if not run:
        raise HTTPException(404, "Optimization run not found")

    db.query(PromptOptimizationCandidate).filter(
        PromptOptimizationCandidate.optimization_run_id == run_id,
    ).delete()
    db.delete(run)
    db.commit()
    logger.info(f"[GEPA] Deleted optimization run {run_id}")
    return


@router.get("/runs/{run_id}/candidates", response_model=List[CandidateResponse])
def list_run_candidates(
    run_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """List all candidates for an optimization run."""
    run = db.query(PromptOptimizationRun).filter(
        PromptOptimizationRun.id == run_id,
        PromptOptimizationRun.organization_id == organization_id,
    ).first()
    if not run:
        raise HTTPException(404, "Optimization run not found")

    return (
        db.query(PromptOptimizationCandidate)
        .filter(PromptOptimizationCandidate.optimization_run_id == run_id)
        .order_by(PromptOptimizationCandidate.score.desc().nullslast())
        .all()
    )


@router.post("/runs/{run_id}/candidates/{candidate_id}/accept")
def accept_candidate(
    run_id: UUID,
    candidate_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Accept a candidate prompt for deployment."""
    candidate = _get_candidate(db, run_id, candidate_id, organization_id)

    db.query(PromptOptimizationCandidate).filter(
        PromptOptimizationCandidate.optimization_run_id == run_id,
    ).update({"is_accepted": False})

    candidate.is_accepted = True
    db.commit()
    return {"message": "Candidate accepted", "candidate_id": str(candidate.id)}


@router.post("/runs/{run_id}/candidates/{candidate_id}/push")
def push_candidate_to_provider(
    run_id: UUID,
    candidate_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Push an accepted candidate prompt to the voice provider (Vapi/Retell/ElevenLabs)."""
    candidate = _get_candidate(db, run_id, candidate_id, organization_id)

    if not candidate.is_accepted:
        raise HTTPException(400, "Candidate must be accepted before pushing to provider")

    run = candidate.optimization_run
    agent = db.query(Agent).filter(Agent.id == run.agent_id).first()
    if not agent:
        raise HTTPException(404, "Agent not found")

    if not agent.voice_ai_integration_id or not agent.voice_ai_agent_id:
        raise HTTPException(400, "Agent is not linked to an external voice provider")

    integration = db.query(Integration).filter(
        Integration.id == agent.voice_ai_integration_id,
    ).first()
    if not integration:
        raise HTTPException(404, "Voice integration not found")

    try:
        decrypted_key = decrypt_api_key(integration.api_key)
        provider_class = get_voice_provider(integration.platform)

        platform_val = integration.platform.value if hasattr(integration.platform, "value") else integration.platform
        if platform_val.lower() == "vapi":
            provider = provider_class(api_key=decrypted_key, public_key=integration.public_key)
        else:
            provider = provider_class(api_key=decrypted_key)

        result = provider.update_agent_prompt(
            agent_id=agent.voice_ai_agent_id,
            system_prompt=candidate.prompt_text,
        )
    except Exception as e:
        raise HTTPException(500, f"Failed to push prompt to provider: {str(e)}")

    candidate.pushed_to_provider_at = datetime.now(timezone.utc)

    agent.description = candidate.prompt_text
    agent.provider_prompt = candidate.prompt_text
    agent.provider_prompt_synced_at = datetime.now(timezone.utc)
    db.commit()

    return {
        "message": f"Prompt pushed to {platform_val} and agent description updated",
        "candidate_id": str(candidate.id),
        "provider_response": result,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_candidate(
    db: Session,
    run_id: UUID,
    candidate_id: UUID,
    organization_id: UUID,
) -> PromptOptimizationCandidate:
    run = db.query(PromptOptimizationRun).filter(
        PromptOptimizationRun.id == run_id,
        PromptOptimizationRun.organization_id == organization_id,
    ).first()
    if not run:
        raise HTTPException(404, "Optimization run not found")

    candidate = db.query(PromptOptimizationCandidate).filter(
        PromptOptimizationCandidate.id == candidate_id,
        PromptOptimizationCandidate.optimization_run_id == run_id,
    ).first()
    if not candidate:
        raise HTTPException(404, "Candidate not found")

    return candidate
