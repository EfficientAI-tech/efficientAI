"""Evaluator routes."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session
from sqlalchemy import and_
from uuid import UUID, uuid4
import random
from typing import List
from pydantic import BaseModel
from loguru import logger

from app.database import get_db
from app.dependencies import get_organization_id, get_workspace_id, get_api_key
from app.services.evaluators.evaluator_helpers import generate_unique_evaluator_id, is_custom_evaluator, validate_metric_ids
from app.services.evaluators.evaluator_run_service import queue_evaluator_runs
from app.services.billing.flexprice_service import record_evaluator_run_requested
from app.models.database import Evaluator, Agent, Persona, Scenario, EvaluatorResult, EvaluatorResultStatus, VoiceBundle, Metric
from app.models.schemas import (
    EvaluatorCreate,
    EvaluatorUpdate,
    EvaluatorResponse,
    EvaluatorBulkCreate,
    RunEvaluatorsRequest,
    RunEvaluatorsResponse,
    EvaluatorResultResponse,
)

router = APIRouter(prefix="/evaluators", tags=["evaluators"])


class FormatPromptRequest(BaseModel):
    prompt: str


class FormatPromptResponse(BaseModel):
    formatted_prompt: str


@router.post("/format-prompt", response_model=FormatPromptResponse)
def format_custom_prompt(
    data: FormatPromptRequest,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Reformat a raw custom prompt into well-structured markdown using the org's LLM."""
    from app.services.ai.llm_service import llm_service
    from app.models.database import AIProvider
    from app.models.enums import ModelProvider

    if not data.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt text is required")

    openai_provider = db.query(AIProvider).filter(
        AIProvider.organization_id == organization_id,
        AIProvider.is_active == True,
        AIProvider.provider == ModelProvider.OPENAI.value,
    ).first()

    if not openai_provider:
        raise HTTPException(
            status_code=400,
            detail="No active OpenAI provider configured. Add one in AI Providers to use AI formatting.",
        )

    messages = [
        {
            "role": "system",
            "content": (
                "You are a technical writer. Your job is to take a raw agent prompt or description "
                "and reformat it into clean, well-structured markdown that an LLM evaluator can "
                "easily parse. Organize the content into clear sections using markdown headings, "
                "bullet points, and numbered lists where appropriate. Preserve ALL original meaning "
                "and details — do not add, remove, or fabricate any information. "
                "Return ONLY the formatted markdown, no preamble or explanation."
            ),
        },
        {"role": "user", "content": data.prompt},
    ]

    try:
        result = llm_service.generate_response(
            messages=messages,
            llm_provider=ModelProvider.OPENAI,
            llm_model="gpt-4o-mini",
            organization_id=organization_id,
            db=db,
            temperature=0.3,
            max_tokens=4000,
        )
        return FormatPromptResponse(formatted_prompt=result["text"])
    except Exception as e:
        logger.error(f"Failed to format prompt: {repr(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to format prompt: {str(e)}")


@router.post("", response_model=EvaluatorResponse, status_code=201)
def create_evaluator(
    evaluator_data: EvaluatorCreate,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Create a single standard evaluator (legacy). Use POST /evaluator-suites for new setups."""
    if bool(evaluator_data.custom_prompt) or (
        evaluator_data.metric_ids and not evaluator_data.agent_id
    ):
        raise HTTPException(
            status_code=400,
            detail="Custom evaluators are no longer supported. Create an evaluator suite instead.",
        )

    if not evaluator_data.agent_id or not evaluator_data.persona_id or not evaluator_data.scenario_id:
        raise HTTPException(
            status_code=400,
            detail="agent_id, persona_id, and scenario_id are required",
        )

    validated_metric_ids = validate_metric_ids(
        db, organization_id, evaluator_data.metric_ids
    ) if evaluator_data.metric_ids else None

    agent = db.query(Agent).filter(
        and_(
            Agent.id == evaluator_data.agent_id,
            Agent.organization_id == organization_id,
            Agent.workspace_id == workspace_id,
        )
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    persona = db.query(Persona).filter(
        and_(
            Persona.id == evaluator_data.persona_id,
            Persona.organization_id == organization_id,
            Persona.workspace_id == workspace_id,
        )
    ).first()
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")

    scenario = db.query(Scenario).filter(
        and_(
            Scenario.id == evaluator_data.scenario_id,
            Scenario.organization_id == organization_id,
            Scenario.workspace_id == workspace_id,
        )
    ).first()
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")

    if agent.voice_bundle_id and persona.tts_provider:
        voice_bundle = db.query(VoiceBundle).filter(VoiceBundle.id == agent.voice_bundle_id).first()
        if voice_bundle and voice_bundle.tts_provider:
            vb_provider = (voice_bundle.tts_provider.value if hasattr(voice_bundle.tts_provider, "value") else str(voice_bundle.tts_provider)).lower()
            persona_provider = persona.tts_provider.lower()
            if vb_provider != persona_provider:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Persona '{persona.name}' uses TTS provider '{persona.tts_provider}' "
                        f"but agent '{agent.name}' voice bundle uses '{voice_bundle.tts_provider}'. "
                        f"The persona's TTS provider must match the agent's voice bundle TTS provider."
                    )
                )

    evaluator_id = generate_unique_evaluator_id(db)

    evaluator = Evaluator(
        evaluator_id=evaluator_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
        name=evaluator_data.name,
        agent_id=evaluator_data.agent_id,
        persona_id=evaluator_data.persona_id,
        scenario_id=evaluator_data.scenario_id,
        metric_ids=validated_metric_ids,
        llm_provider=evaluator_data.llm_provider.value if evaluator_data.llm_provider else None,
        llm_model=evaluator_data.llm_model,
        llm_config=evaluator_data.llm_config,
        tags=evaluator_data.tags,
    )
    db.add(evaluator)
    db.commit()
    db.refresh(evaluator)

    return evaluator


@router.post("/bulk", response_model=List[EvaluatorResponse], status_code=201, deprecated=True)
def create_evaluators_bulk(
    bulk_data: EvaluatorBulkCreate,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Create multiple evaluators in the active workspace for the same agent/scenario."""
    agent = db.query(Agent).filter(
        and_(
            Agent.id == bulk_data.agent_id,
            Agent.organization_id == organization_id,
            Agent.workspace_id == workspace_id,
        )
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    scenario = db.query(Scenario).filter(
        and_(
            Scenario.id == bulk_data.scenario_id,
            Scenario.organization_id == organization_id,
            Scenario.workspace_id == workspace_id,
        )
    ).first()
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")

    personas = db.query(Persona).filter(
        and_(
            Persona.id.in_(bulk_data.persona_ids),
            Persona.organization_id == organization_id,
            Persona.workspace_id == workspace_id,
        )
    ).all()
    if len(personas) != len(bulk_data.persona_ids):
        raise HTTPException(status_code=404, detail="One or more personas not found")

    # Validate TTS provider compatibility between personas and voice bundle
    if agent.voice_bundle_id:
        voice_bundle = db.query(VoiceBundle).filter(VoiceBundle.id == agent.voice_bundle_id).first()
        if voice_bundle and voice_bundle.tts_provider:
            vb_provider = (voice_bundle.tts_provider.value if hasattr(voice_bundle.tts_provider, "value") else str(voice_bundle.tts_provider)).lower()
            mismatched = [
                p.name for p in personas
                if p.tts_provider and p.tts_provider.lower() != vb_provider
            ]
            if mismatched:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"The following personas use a different TTS provider than the agent's voice bundle "
                        f"('{voice_bundle.tts_provider}'): {', '.join(mismatched)}. "
                        f"All personas must use a TTS provider that matches the agent's voice bundle."
                    )
                )

    # Create evaluators for each persona
    evaluators = []
    for persona_id in bulk_data.persona_ids:
        evaluator_id = generate_unique_evaluator_id(db)
        evaluator = Evaluator(
            evaluator_id=evaluator_id,
            organization_id=organization_id,
            workspace_id=workspace_id,
            name=bulk_data.name,
            agent_id=bulk_data.agent_id,
            persona_id=persona_id,
            scenario_id=bulk_data.scenario_id,
            tags=bulk_data.tags,
        )
        db.add(evaluator)
        evaluators.append(evaluator)

    db.commit()
    for evaluator in evaluators:
        db.refresh(evaluator)

    return evaluators


@router.get("", response_model=List[EvaluatorResponse])
def list_evaluators(
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """List evaluators in the active workspace."""
    evaluators = db.query(Evaluator).filter(
        Evaluator.organization_id == organization_id,
        Evaluator.workspace_id == workspace_id,
    ).order_by(Evaluator.created_at.desc()).all()
    return evaluators


@router.get("/{evaluator_id}", response_model=EvaluatorResponse)
def get_evaluator(
    evaluator_id: str,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Get an evaluator in the active workspace by UUID or evaluator_id (6-digit)."""
    try:
        evaluator_uuid = UUID(evaluator_id)
        evaluator = db.query(Evaluator).filter(
            and_(
                Evaluator.id == evaluator_uuid,
                Evaluator.organization_id == organization_id,
                Evaluator.workspace_id == workspace_id,
            )
        ).first()
    except ValueError:
        evaluator = db.query(Evaluator).filter(
            and_(
                Evaluator.evaluator_id == evaluator_id,
                Evaluator.organization_id == organization_id,
                Evaluator.workspace_id == workspace_id,
            )
        ).first()

    if not evaluator:
        raise HTTPException(status_code=404, detail="Evaluator not found")

    return evaluator


@router.put("/{evaluator_id}", response_model=EvaluatorResponse)
def update_evaluator(
    evaluator_id: str,
    evaluator_data: EvaluatorUpdate,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Update an evaluator within the active workspace."""
    try:
        evaluator_uuid = UUID(evaluator_id)
        evaluator = db.query(Evaluator).filter(
            and_(
                Evaluator.id == evaluator_uuid,
                Evaluator.organization_id == organization_id,
                Evaluator.workspace_id == workspace_id,
            )
        ).first()
    except ValueError:
        evaluator = db.query(Evaluator).filter(
            and_(
                Evaluator.evaluator_id == evaluator_id,
                Evaluator.organization_id == organization_id,
                Evaluator.workspace_id == workspace_id,
            )
        ).first()

    if not evaluator:
        raise HTTPException(status_code=404, detail="Evaluator not found")

    # Re-validate any newly-referenced resources against the active workspace
    # to prevent cross-workspace pointer attacks (assigning a foreign workspace's
    # agent to this evaluator).
    if evaluator_data.agent_id is not None:
        agent = db.query(Agent).filter(
            and_(
                Agent.id == evaluator_data.agent_id,
                Agent.organization_id == organization_id,
                Agent.workspace_id == workspace_id,
            )
        ).first()
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        evaluator.agent_id = evaluator_data.agent_id

    if evaluator_data.persona_id is not None:
        persona = db.query(Persona).filter(
            and_(
                Persona.id == evaluator_data.persona_id,
                Persona.organization_id == organization_id,
                Persona.workspace_id == workspace_id,
            )
        ).first()
        if not persona:
            raise HTTPException(status_code=404, detail="Persona not found")
        evaluator.persona_id = evaluator_data.persona_id

    if evaluator_data.scenario_id is not None:
        scenario = db.query(Scenario).filter(
            and_(
                Scenario.id == evaluator_data.scenario_id,
                Scenario.organization_id == organization_id,
                Scenario.workspace_id == workspace_id,
            )
        ).first()
        if not scenario:
            raise HTTPException(status_code=404, detail="Scenario not found")
        evaluator.scenario_id = evaluator_data.scenario_id

    if evaluator_data.tags is not None:
        evaluator.tags = evaluator_data.tags

    if evaluator_data.name is not None:
        evaluator.name = evaluator_data.name

    if evaluator_data.custom_prompt is not None:
        evaluator.custom_prompt = evaluator_data.custom_prompt

    if evaluator_data.metric_ids is not None:
        if evaluator_data.metric_ids:
            metric_uuids = list({m for m in evaluator_data.metric_ids})
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
            evaluator.metric_ids = [str(mid) for mid in metric_uuids]
        else:
            evaluator.metric_ids = None

    if evaluator_data.llm_provider is not None:
        evaluator.llm_provider = evaluator_data.llm_provider.value
    
    if evaluator_data.llm_model is not None:
        evaluator.llm_model = evaluator_data.llm_model

    if evaluator_data.llm_config is not None:
        evaluator.llm_config = evaluator_data.llm_config

    db.commit()
    db.refresh(evaluator)

    return evaluator


@router.delete("/{evaluator_id}")
def delete_evaluator(
    evaluator_id: str,
    force: bool = Query(False, description="Deprecated: evaluator deletion keeps dependent results"),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Delete an evaluator in the active workspace while preserving dependent results."""
    try:
        evaluator_uuid = UUID(evaluator_id)
        evaluator = db.query(Evaluator).filter(
            and_(
                Evaluator.id == evaluator_uuid,
                Evaluator.organization_id == organization_id,
                Evaluator.workspace_id == workspace_id,
            )
        ).first()
    except ValueError:
        evaluator = db.query(Evaluator).filter(
            and_(
                Evaluator.evaluator_id == evaluator_id,
                Evaluator.organization_id == organization_id,
                Evaluator.workspace_id == workspace_id,
            )
        ).first()

    if not evaluator:
        raise HTTPException(status_code=404, detail="Evaluator not found")

    evaluator_results_count = db.query(EvaluatorResult).filter(
        EvaluatorResult.evaluator_id == evaluator.id
    ).count()

    dependencies = {}
    if evaluator_results_count > 0:
        dependencies["evaluator_results"] = evaluator_results_count
        # Preserve historical results by detaching them from this evaluator.
        db.query(EvaluatorResult).filter(
            EvaluatorResult.evaluator_id == evaluator.id
        ).update({EvaluatorResult.evaluator_id: None}, synchronize_session=False)

    db.delete(evaluator)
    db.commit()

    if dependencies:
        return JSONResponse(
            status_code=200,
            content={
                "message": "Evaluator deleted successfully. Dependent evaluator results were preserved and detached.",
                "detached": dependencies,
            },
        )

    return Response(status_code=204)


@router.post("/run", response_model=RunEvaluatorsResponse, status_code=200)
def run_evaluators(
    request: RunEvaluatorsRequest,
    background_tasks: BackgroundTasks,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Run multiple evaluators in the active workspace in parallel using Celery workers."""
    if not request.evaluator_ids:
        raise HTTPException(status_code=400, detail="No evaluator IDs provided")

    task_ids, evaluator_results = queue_evaluator_runs(
        db, organization_id, workspace_id, request.evaluator_ids
    )

    background_tasks.add_task(
        record_evaluator_run_requested,
        organization_id,
        uuid4(),
        workspace_id=workspace_id,
        quantity=len(task_ids),
    )

    return RunEvaluatorsResponse(
        task_ids=task_ids,
        evaluator_results=evaluator_results,
    )


from app.core.auth.capabilities import SIM_MANAGE, SIM_VIEW
from app.core.auth.workspace_route_capabilities import apply_workspace_route_capabilities

apply_workspace_route_capabilities(
    router,
    view_capability=SIM_VIEW,
    manage_capability=SIM_MANAGE,
)

