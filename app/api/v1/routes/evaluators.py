"""Evaluator routes."""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import and_
from uuid import UUID
import random
from typing import List
from pydantic import BaseModel
from loguru import logger

from app.database import get_db
from app.dependencies import get_organization_id, get_api_key
from app.models.database import Evaluator, Agent, Persona, Scenario, EvaluatorResult, EvaluatorResultStatus
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


def generate_unique_evaluator_id(db: Session) -> str:
    """Generate a unique 6-digit evaluator ID."""
    max_attempts = 100
    for _ in range(max_attempts):
        evaluator_id = f"{random.randint(100000, 999999)}"
        existing = db.query(Evaluator).filter(Evaluator.evaluator_id == evaluator_id).first()
        if not existing:
            return evaluator_id
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Failed to generate unique evaluator ID"
    )


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
    from app.services.llm_service import llm_service
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
    db: Session = Depends(get_db),
):
    """Create a new evaluator. Supports standard (agent+persona+scenario) or custom (custom_prompt) mode."""
    is_custom = bool(evaluator_data.custom_prompt)
    
    if is_custom:
        if not evaluator_data.name:
            raise HTTPException(status_code=400, detail="Name is required for custom evaluators")
    else:
        if not evaluator_data.agent_id or not evaluator_data.persona_id or not evaluator_data.scenario_id:
            raise HTTPException(
                status_code=400,
                detail="agent_id, persona_id, and scenario_id are required for standard evaluators"
            )
        
        agent = db.query(Agent).filter(
            and_(Agent.id == evaluator_data.agent_id, Agent.organization_id == organization_id)
        ).first()
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        persona = db.query(Persona).filter(
            and_(Persona.id == evaluator_data.persona_id, Persona.organization_id == organization_id)
        ).first()
        if not persona:
            raise HTTPException(status_code=404, detail="Persona not found")

        scenario = db.query(Scenario).filter(
            and_(Scenario.id == evaluator_data.scenario_id, Scenario.organization_id == organization_id)
        ).first()
        if not scenario:
            raise HTTPException(status_code=404, detail="Scenario not found")

    evaluator_id = generate_unique_evaluator_id(db)

    evaluator = Evaluator(
        evaluator_id=evaluator_id,
        organization_id=organization_id,
        name=evaluator_data.name,
        agent_id=evaluator_data.agent_id if not is_custom else None,
        persona_id=evaluator_data.persona_id if not is_custom else None,
        scenario_id=evaluator_data.scenario_id if not is_custom else None,
        custom_prompt=evaluator_data.custom_prompt if is_custom else None,
        llm_provider=evaluator_data.llm_provider.value if evaluator_data.llm_provider else None,
        llm_model=evaluator_data.llm_model,
        tags=evaluator_data.tags,
    )
    db.add(evaluator)
    db.commit()
    db.refresh(evaluator)

    return evaluator


@router.post("/bulk", response_model=List[EvaluatorResponse], status_code=201)
def create_evaluators_bulk(
    bulk_data: EvaluatorBulkCreate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Create multiple evaluators for a scenario with multiple personas."""
    # Verify agent exists and belongs to organization
    agent = db.query(Agent).filter(
        and_(Agent.id == bulk_data.agent_id, Agent.organization_id == organization_id)
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Verify scenario exists and belongs to organization
    scenario = db.query(Scenario).filter(
        and_(Scenario.id == bulk_data.scenario_id, Scenario.organization_id == organization_id)
    ).first()
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")

    # Verify all personas exist and belong to organization
    personas = db.query(Persona).filter(
        and_(Persona.id.in_(bulk_data.persona_ids), Persona.organization_id == organization_id)
    ).all()
    if len(personas) != len(bulk_data.persona_ids):
        raise HTTPException(status_code=404, detail="One or more personas not found")

    # Create evaluators for each persona
    evaluators = []
    for persona_id in bulk_data.persona_ids:
        evaluator_id = generate_unique_evaluator_id(db)
        evaluator = Evaluator(
            evaluator_id=evaluator_id,
            organization_id=organization_id,
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
    db: Session = Depends(get_db),
):
    """List all evaluators for the organization."""
    evaluators = db.query(Evaluator).filter(
        Evaluator.organization_id == organization_id
    ).order_by(Evaluator.created_at.desc()).all()
    return evaluators


@router.get("/{evaluator_id}", response_model=EvaluatorResponse)
def get_evaluator(
    evaluator_id: str,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Get a specific evaluator by ID (UUID) or evaluator_id (6-digit)."""
    # Try UUID first
    try:
        evaluator_uuid = UUID(evaluator_id)
        evaluator = db.query(Evaluator).filter(
            and_(
                Evaluator.id == evaluator_uuid,
                Evaluator.organization_id == organization_id
            )
        ).first()
    except ValueError:
        # Not a UUID, try 6-digit ID
        evaluator = db.query(Evaluator).filter(
            and_(
                Evaluator.evaluator_id == evaluator_id,
                Evaluator.organization_id == organization_id
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
    db: Session = Depends(get_db),
):
    """Update an evaluator."""
    # Try UUID first
    try:
        evaluator_uuid = UUID(evaluator_id)
        evaluator = db.query(Evaluator).filter(
            and_(
                Evaluator.id == evaluator_uuid,
                Evaluator.organization_id == organization_id
            )
        ).first()
    except ValueError:
        # Not a UUID, try 6-digit ID
        evaluator = db.query(Evaluator).filter(
            and_(
                Evaluator.evaluator_id == evaluator_id,
                Evaluator.organization_id == organization_id
            )
        ).first()

    if not evaluator:
        raise HTTPException(status_code=404, detail="Evaluator not found")

    # Update fields if provided
    if evaluator_data.agent_id is not None:
        agent = db.query(Agent).filter(
            and_(Agent.id == evaluator_data.agent_id, Agent.organization_id == organization_id)
        ).first()
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        evaluator.agent_id = evaluator_data.agent_id

    if evaluator_data.persona_id is not None:
        persona = db.query(Persona).filter(
            and_(Persona.id == evaluator_data.persona_id, Persona.organization_id == organization_id)
        ).first()
        if not persona:
            raise HTTPException(status_code=404, detail="Persona not found")
        evaluator.persona_id = evaluator_data.persona_id

    if evaluator_data.scenario_id is not None:
        scenario = db.query(Scenario).filter(
            and_(Scenario.id == evaluator_data.scenario_id, Scenario.organization_id == organization_id)
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

    if evaluator_data.llm_provider is not None:
        evaluator.llm_provider = evaluator_data.llm_provider.value
    
    if evaluator_data.llm_model is not None:
        evaluator.llm_model = evaluator_data.llm_model

    db.commit()
    db.refresh(evaluator)

    return evaluator


@router.delete("/{evaluator_id}")
def delete_evaluator(
    evaluator_id: str,
    force: bool = Query(False, description="Force delete with all dependent records"),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Delete an evaluator. Returns 409 if dependent records exist unless force=true."""
    try:
        evaluator_uuid = UUID(evaluator_id)
        evaluator = db.query(Evaluator).filter(
            and_(
                Evaluator.id == evaluator_uuid,
                Evaluator.organization_id == organization_id
            )
        ).first()
    except ValueError:
        evaluator = db.query(Evaluator).filter(
            and_(
                Evaluator.evaluator_id == evaluator_id,
                Evaluator.organization_id == organization_id
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

    if dependencies and not force:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": f"Cannot delete evaluator. It has {evaluator_results_count} evaluator result(s).",
                "dependencies": dependencies,
                "hint": "Use force=true to delete this evaluator and all its dependent records.",
            },
        )

    if dependencies:
        db.query(EvaluatorResult).filter(
            EvaluatorResult.evaluator_id == evaluator.id
        ).delete(synchronize_session=False)

    db.delete(evaluator)
    db.commit()

    if dependencies:
        return JSONResponse(
            status_code=200,
            content={
                "message": "Evaluator and all dependent records deleted successfully.",
                "deleted": dependencies,
            },
        )

    return JSONResponse(status_code=204, content=None)


@router.post("/run", response_model=RunEvaluatorsResponse, status_code=200)
def run_evaluators(
    request: RunEvaluatorsRequest,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Run multiple evaluators in parallel using Celery workers.
    
    The same evaluator ID can appear multiple times in the request to run
    the same evaluator multiple times in parallel.
    """
    from app.workers.celery_app import run_evaluator_task
    
    if not request.evaluator_ids:
        raise HTTPException(status_code=400, detail="No evaluator IDs provided")
    
    task_ids = []
    evaluator_results = []
    
    # Get unique evaluator IDs for validation
    unique_evaluator_ids = list(set(request.evaluator_ids))
    
    # Validate all unique evaluators exist and belong to organization
    evaluators = db.query(Evaluator).filter(
        and_(
            Evaluator.id.in_(unique_evaluator_ids),
            Evaluator.organization_id == organization_id
        )
    ).all()
    
    if len(evaluators) != len(unique_evaluator_ids):
        raise HTTPException(
            status_code=404,
            detail=f"One or more evaluators not found. Found {len(evaluators)} of {len(unique_evaluator_ids)} unique evaluators"
        )
    
    # Create a lookup map for quick access
    evaluator_map = {str(e.id): e for e in evaluators}
    
    # Create Celery tasks for each evaluator ID in the request (including duplicates)
    for evaluator_id in request.evaluator_ids:
        evaluator = evaluator_map.get(str(evaluator_id))
        if not evaluator:
            continue
            
        try:
            is_custom = bool(evaluator.custom_prompt)
            if is_custom:
                scenario_name = evaluator.name or "Custom Evaluation"
            else:
                scenario = db.query(Scenario).filter(Scenario.id == evaluator.scenario_id).first()
                scenario_name = scenario.name if scenario else "Unknown Scenario"
            
            # Generate unique 6-digit result ID
            max_attempts = 100
            result_id = None
            for _ in range(max_attempts):
                candidate_id = f"{random.randint(100000, 999999)}"
                existing = db.query(EvaluatorResult).filter(EvaluatorResult.result_id == candidate_id).first()
                if not existing:
                    result_id = candidate_id
                    break
            
            if not result_id:
                raise HTTPException(status_code=500, detail="Failed to generate unique result ID")
            
            # Create placeholder result
            evaluator_result = EvaluatorResult(
                result_id=result_id,
                organization_id=organization_id,
                evaluator_id=evaluator.id,
                agent_id=evaluator.agent_id,
                persona_id=evaluator.persona_id,
                scenario_id=evaluator.scenario_id,
                name=scenario_name,
                status=EvaluatorResultStatus.QUEUED.value,
                audio_s3_key=None,  # Will be set by task
            )
            db.add(evaluator_result)
            db.commit()
            db.refresh(evaluator_result)
            
            # Trigger Celery task
            task = run_evaluator_task.delay(str(evaluator.id), str(evaluator_result.id))
            task_ids.append(task.id)
            
            # Update result with task ID
            evaluator_result.celery_task_id = task.id
            db.commit()
            
            # Convert to response model
            evaluator_results.append(EvaluatorResultResponse.model_validate(evaluator_result))
            
        except Exception as e:
            # Use repr(e) to escape curly braces that could break loguru formatting
            logger.error(f"Error creating task for evaluator {evaluator.id}: {repr(e)}", exc_info=True)
            # Continue with other evaluators even if one fails
            continue
    
    if not task_ids:
        raise HTTPException(status_code=500, detail="Failed to create any tasks")
    
    return RunEvaluatorsResponse(
        task_ids=task_ids,
        evaluator_results=evaluator_results
    )

