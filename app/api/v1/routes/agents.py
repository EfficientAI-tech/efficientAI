"""
Agents API Routes
Complete CRUD operations for test agents
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID
import random
from pydantic import BaseModel
from loguru import logger

from app.dependencies import get_db, get_organization_id, get_api_key
from app.models.database import (
    Agent, ConversationEvaluation, TestAgentConversation, VoiceBundle,
    AIProvider, Integration, IntegrationPlatform, CallMediumEnum,
    Evaluator, EvaluatorResult, CallRecording,
)
from sqlalchemy import and_
from app.models.schemas import (
    AgentCreate, AgentUpdate, AgentResponse, CallMediumEnum as CallMediumEnumSchema
)

router = APIRouter(prefix="/agents", tags=["agents"])


# ======================================================================
# AI Generation for agent descriptions
# ======================================================================

class GenerateAgentDescriptionRequest(BaseModel):
    description: str
    tone: Optional[str] = "professional"
    format_style: Optional[str] = "structured"
    provider: Optional[str] = None
    model: Optional[str] = None


GENERATE_AGENT_DESCRIPTION_SYSTEM = (
    "You are an expert at writing clear, well-structured descriptions for voice AI test agents. "
    "The user will describe what they need the agent to do, and you will generate a comprehensive, "
    "well-formatted agent description in markdown.\n\n"
    "Guidelines:\n"
    "- Use clear markdown structure: headings, bullet points, numbered lists\n"
    "- Include sections for: Purpose, Behavior, Expected Interactions, Personality Traits, and Constraints\n"
    "- Be specific about the agent's role, tone of voice, and how it should handle conversations\n"
    "- Include example scenarios or edge cases where helpful\n"
    "- Return ONLY the description in markdown, no preamble or explanation about what you did"
)


def _get_llm_provider_and_model(
    organization_id: UUID,
    db: Session,
    provider: Optional[str] = None,
    model: Optional[str] = None,
):
    """Resolve the LLM provider and model to use, falling back to org defaults."""
    from app.models.database import AIProvider
    from app.models.enums import ModelProvider

    if provider and model:
        try:
            provider_enum = ModelProvider(provider.lower())
        except ValueError:
            raise HTTPException(400, f"Unsupported LLM provider: {provider}")
        return provider_enum, model

    for prov in [ModelProvider.OPENAI, ModelProvider.ANTHROPIC, ModelProvider.GOOGLE]:
        ai_prov = db.query(AIProvider).filter(
            AIProvider.organization_id == organization_id,
            AIProvider.is_active == True,
            AIProvider.provider == prov.value,
        ).first()
        if ai_prov:
            default_models = {
                ModelProvider.OPENAI: "gpt-5-mini",
                ModelProvider.ANTHROPIC: "claude-sonnet-4-20250514",
                ModelProvider.GOOGLE: "gemini-2.0-flash",
            }
            return prov, model or default_models.get(prov, "gpt-5-mini")

    raise HTTPException(
        400,
        "No active AI provider configured. Add an OpenAI, Anthropic, or Google provider in AI Providers settings.",
    )


@router.post("/generate-description")
async def generate_agent_description(
    data: GenerateAgentDescriptionRequest,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Generate an agent description using AI from a brief description."""
    from app.services.ai.llm_service import llm_service

    if not data.description.strip():
        raise HTTPException(400, "Description is required")

    provider_enum, model_str = _get_llm_provider_and_model(
        organization_id, db, data.provider, data.model
    )

    user_prompt = (
        f"Create a detailed agent description for the following:\n\n"
        f"Description: {data.description}\n"
        f"Tone: {data.tone or 'professional'}\n"
        f"Format: {data.format_style or 'structured'}\n\n"
        f"Generate a comprehensive, well-formatted agent description in markdown."
    )

    messages = [
        {"role": "system", "content": GENERATE_AGENT_DESCRIPTION_SYSTEM},
        {"role": "user", "content": user_prompt},
    ]

    try:
        result = llm_service.generate_response(
            messages=messages,
            llm_provider=provider_enum,
            llm_model=model_str,
            organization_id=organization_id,
            db=db,
            temperature=0.7,
            max_tokens=4000,
        )
        return {"content": result["text"], "provider": provider_enum.value, "model": model_str}
    except Exception as e:
        logger.error(f"[Agents] AI description generation failed: {repr(e)}")
        raise HTTPException(500, f"AI generation failed: {str(e)}")


def generate_unique_agent_id(db: Session) -> str:
    """Generate a unique 6-digit agent ID."""
    max_attempts = 100
    for _ in range(max_attempts):
        agent_id = f"{random.randint(100000, 999999)}"
        existing = db.query(Agent).filter(Agent.agent_id == agent_id).first()
        if not existing:
            return agent_id
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Failed to generate unique agent ID"
    )


def get_agent_dependencies(db: Session, organization_id: UUID, agent_uuid: UUID) -> dict:
    """Return dependency counts that block non-force delete."""
    evaluators_count = db.query(Evaluator).filter(
        Evaluator.agent_id == agent_uuid,
        Evaluator.organization_id == organization_id,
    ).count()

    evaluator_results_count = db.query(EvaluatorResult).filter(
        EvaluatorResult.agent_id == agent_uuid,
        EvaluatorResult.organization_id == organization_id,
    ).count()

    call_recordings_count = db.query(CallRecording).filter(
        CallRecording.agent_id == agent_uuid,
        CallRecording.organization_id == organization_id,
    ).count()

    conversation_evaluations_count = db.query(ConversationEvaluation).filter(
        ConversationEvaluation.agent_id == agent_uuid,
        ConversationEvaluation.organization_id == organization_id,
    ).count()

    test_conversations_count = db.query(TestAgentConversation).filter(
        TestAgentConversation.agent_id == agent_uuid,
        TestAgentConversation.organization_id == organization_id,
    ).count()

    dependencies = {}
    if evaluators_count > 0:
        dependencies["evaluators"] = evaluators_count
    if evaluator_results_count > 0:
        dependencies["evaluator_results"] = evaluator_results_count
    if call_recordings_count > 0:
        dependencies["call_recordings"] = call_recordings_count
    if conversation_evaluations_count > 0:
        dependencies["conversation_evaluations"] = conversation_evaluations_count
    if test_conversations_count > 0:
        dependencies["test_conversations"] = test_conversations_count

    return dependencies


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(
    agent: AgentCreate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Create a new test agent"""
    # Validate phone_number is provided when call_medium is phone_call
    if agent.call_medium == CallMediumEnumSchema.PHONE_CALL and not agent.phone_number:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="phone_number is required when call_medium is phone_call"
        )
    
    # Validate voice_bundle_id exists and belongs to organization
    if agent.voice_bundle_id:
        voice_bundle = db.query(VoiceBundle).filter(
            and_(
                VoiceBundle.id == agent.voice_bundle_id,
                VoiceBundle.organization_id == organization_id
            )
        ).first()
        if not voice_bundle:
            raise HTTPException(status_code=404, detail="Voice bundle not found")
    
    # Validate voice_ai_integration_id exists and belongs to organization
    if agent.voice_ai_integration_id:
        integration = db.query(Integration).filter(
            and_(
                Integration.id == agent.voice_ai_integration_id,
                Integration.organization_id == organization_id,
                Integration.is_active == True
            )
        ).first()
        if not integration:
            raise HTTPException(status_code=404, detail="Integration not found or inactive")
        
        if integration.platform not in [
            IntegrationPlatform.RETELL,
            IntegrationPlatform.VAPI,
            IntegrationPlatform.ELEVENLABS,
            IntegrationPlatform.SMALLEST,
        ]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Integration platform {integration.platform.value} is not supported for Voice AI agents. "
                    "Only Retell, Vapi, ElevenLabs, and Smallest are supported."
                )
            )
        
        if not agent.voice_ai_agent_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="voice_ai_agent_id is required when voice_ai_integration_id is provided"
            )
    
    # Generate unique 6-digit agent_id
    agent_id = generate_unique_agent_id(db)
    
    db_agent = Agent(
        agent_id=agent_id,
        organization_id=organization_id,
        name=agent.name,
        phone_number=agent.phone_number,
        language=agent.language,
        description=agent.description,
        call_type=agent.call_type,
        call_medium=agent.call_medium,
        voice_bundle_id=agent.voice_bundle_id,
        ai_provider_id=agent.ai_provider_id,
        voice_ai_integration_id=agent.voice_ai_integration_id,
        voice_ai_agent_id=agent.voice_ai_agent_id
    )
    db.add(db_agent)
    db.commit()
    db.refresh(db_agent)

    if agent.voice_ai_integration_id and agent.voice_ai_agent_id:
        try:
            from app.services.voice_providers.prompt_sync import sync_provider_prompt
            integration = db.query(Integration).filter(Integration.id == agent.voice_ai_integration_id).first()
            if integration:
                sync_provider_prompt(db_agent, integration, db)
                db.refresh(db_agent)
        except Exception as e:
            logger.warning(f"[Agents] Best-effort provider prompt sync failed on create: {e}")

    return db_agent


@router.get("", response_model=List[AgentResponse])
async def list_agents(
    skip: int = 0,
    limit: int = 100,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Get list of all agents for the organization"""
    agents = db.query(Agent).filter(
        Agent.organization_id == organization_id
    ).offset(skip).limit(limit).all()
    return agents


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: str,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Get a specific agent by ID (UUID) or agent_id (6-digit)."""
    try:
        # Try as UUID first
        agent_uuid = UUID(agent_id)
        agent = db.query(Agent).filter(
            and_(
                Agent.id == agent_uuid,
                Agent.organization_id == organization_id
            )
        ).first()
    except ValueError:
        # Try as 6-digit ID
        agent = db.query(Agent).filter(
            and_(
                Agent.agent_id == agent_id,
                Agent.organization_id == organization_id
            )
        ).first()
    
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    return agent


@router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str,
    agent_update: AgentUpdate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Update an existing agent by ID (UUID) or agent_id (6-digit)."""
    try:
        # Try as UUID first
        agent_uuid = UUID(agent_id)
        db_agent = db.query(Agent).filter(
            and_(
                Agent.id == agent_uuid,
                Agent.organization_id == organization_id
            )
        ).first()
    except ValueError:
        # Try as 6-digit ID
        db_agent = db.query(Agent).filter(
            and_(
                Agent.agent_id == agent_id,
                Agent.organization_id == organization_id
            )
        ).first()
    
    if not db_agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    
    # Determine the call_medium to validate
    call_medium = agent_update.call_medium if agent_update.call_medium is not None else db_agent.call_medium
    
    # Validate phone_number is provided when call_medium is phone_call
    if call_medium == CallMediumEnum.PHONE_CALL:
        phone_number = agent_update.phone_number if agent_update.phone_number is not None else db_agent.phone_number
        if not phone_number:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="phone_number is required when call_medium is phone_call"
            )
    
    # Validate voice_bundle_id if provided
    if agent_update.voice_bundle_id:
        voice_bundle = db.query(VoiceBundle).filter(
            and_(
                VoiceBundle.id == agent_update.voice_bundle_id,
                VoiceBundle.organization_id == organization_id
            )
        ).first()
        if not voice_bundle:
            raise HTTPException(status_code=404, detail="Voice bundle not found")
    
    # Validate voice_ai_integration_id if provided
    if agent_update.voice_ai_integration_id:
        integration = db.query(Integration).filter(
            and_(
                Integration.id == agent_update.voice_ai_integration_id,
                Integration.organization_id == organization_id,
                Integration.is_active == True
            )
        ).first()
        if not integration:
            raise HTTPException(status_code=404, detail="Integration not found or inactive")
        
        if integration.platform not in [
            IntegrationPlatform.RETELL,
            IntegrationPlatform.VAPI,
            IntegrationPlatform.ELEVENLABS,
            IntegrationPlatform.SMALLEST,
        ]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Integration platform {integration.platform.value} is not supported for Voice AI agents. "
                    "Only Retell, Vapi, ElevenLabs, and Smallest are supported."
                )
            )
        
        if not agent_update.voice_ai_agent_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="voice_ai_agent_id is required when voice_ai_integration_id is provided"
            )
    
    # Convert the update model to dict, handling None values properly
    # Use model_dump with exclude_unset to only get fields that were explicitly provided
    update_data = agent_update.model_dump(exclude_unset=True, exclude_none=False)
    
    # Apply updates
    for field, value in update_data.items():
        setattr(db_agent, field, value)
    
    db.commit()
    db.refresh(db_agent)

    if "voice_ai_agent_id" in update_data or "voice_ai_integration_id" in update_data:
        integration_id = db_agent.voice_ai_integration_id
        if integration_id and db_agent.voice_ai_agent_id:
            try:
                from app.services.voice_providers.prompt_sync import sync_provider_prompt
                integration = db.query(Integration).filter(Integration.id == integration_id).first()
                if integration:
                    sync_provider_prompt(db_agent, integration, db)
                    db.refresh(db_agent)
            except Exception as e:
                logger.warning(f"[Agents] Best-effort provider prompt sync failed on update: {e}")

    return db_agent


@router.post("/{agent_id}/sync-provider-prompt")
async def sync_agent_provider_prompt(
    agent_id: str,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Fetch and store the current system prompt from the voice provider."""
    try:
        agent_uuid = UUID(agent_id)
        db_agent = db.query(Agent).filter(
            and_(Agent.id == agent_uuid, Agent.organization_id == organization_id)
        ).first()
    except ValueError:
        db_agent = db.query(Agent).filter(
            and_(Agent.agent_id == agent_id, Agent.organization_id == organization_id)
        ).first()

    if not db_agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    if not db_agent.voice_ai_integration_id or not db_agent.voice_ai_agent_id:
        raise HTTPException(
            status_code=400,
            detail="Agent is not linked to an external voice provider",
        )

    integration = db.query(Integration).filter(
        and_(
            Integration.id == db_agent.voice_ai_integration_id,
            Integration.organization_id == organization_id,
            Integration.is_active == True,
        )
    ).first()
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found or inactive")

    try:
        from app.services.voice_providers.prompt_sync import sync_provider_prompt
        prompt = sync_provider_prompt(db_agent, integration, db)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch prompt from provider: {str(e)}")

    db.refresh(db_agent)
    return {
        "provider_prompt": db_agent.provider_prompt,
        "provider_prompt_synced_at": db_agent.provider_prompt_synced_at.isoformat() if db_agent.provider_prompt_synced_at else None,
    }


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: str,
    force: bool = Query(False, description="Force delete with all dependent records"),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Delete an agent by ID (UUID) or agent_id (6-digit). Returns 409 if dependent records exist unless force=true."""
    try:
        agent_uuid = UUID(agent_id)
        db_agent = db.query(Agent).filter(
            and_(
                Agent.id == agent_uuid,
                Agent.organization_id == organization_id
            )
        ).first()
    except ValueError:
        db_agent = db.query(Agent).filter(
            and_(
                Agent.agent_id == agent_id,
                Agent.organization_id == organization_id
            )
        ).first()
    
    if not db_agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    
    agent_uuid = db_agent.id
    dependencies = get_agent_dependencies(db, organization_id, agent_uuid)

    if dependencies and not force:
        parts = []
        if dependencies.get("evaluators"):
            parts.append(f"{dependencies['evaluators']} evaluator(s)")
        if dependencies.get("evaluator_results"):
            parts.append(f"{dependencies['evaluator_results']} evaluator result(s)")
        if dependencies.get("call_recordings"):
            parts.append(f"{dependencies['call_recordings']} call recording(s)")
        if dependencies.get("conversation_evaluations"):
            parts.append(f"{dependencies['conversation_evaluations']} conversation evaluation(s)")
        if dependencies.get("test_conversations"):
            parts.append(f"{dependencies['test_conversations']} test conversation(s)")

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": f"Cannot delete agent. It is referenced by: {', '.join(parts)}.",
                "dependencies": dependencies,
                "hint": "Use force=true to delete this agent and all its dependent records.",
            },
        )

    if dependencies:
        # Delete in FK-safe order:
        # 1. EvaluatorResults (references evaluators and agents)
        db.query(EvaluatorResult).filter(
            EvaluatorResult.agent_id == agent_uuid,
        ).delete(synchronize_session=False)

        # 2. Evaluators (references agents)
        db.query(Evaluator).filter(
            Evaluator.agent_id == agent_uuid,
        ).delete(synchronize_session=False)

        # 3. Nullify call recordings (keep recordings, unlink agent)
        db.query(CallRecording).filter(
            CallRecording.agent_id == agent_uuid,
        ).update({CallRecording.agent_id: None}, synchronize_session=False)

        # 4. ConversationEvaluations
        db.query(ConversationEvaluation).filter(
            ConversationEvaluation.agent_id == agent_uuid,
        ).delete(synchronize_session=False)

        # 5. TestAgentConversations
        db.query(TestAgentConversation).filter(
            TestAgentConversation.agent_id == agent_uuid,
        ).delete(synchronize_session=False)

    db.delete(db_agent)
    db.commit()

    if dependencies:
        return JSONResponse(
            status_code=200,
            content={
                "message": "Agent and all dependent records deleted successfully.",
                "deleted": dependencies,
            },
        )

    return Response(status_code=204)


@router.get("/{agent_id}/delete-impact")
async def get_agent_delete_impact(
    agent_id: str,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Preview dependent records that would be affected by force delete."""
    try:
        agent_uuid = UUID(agent_id)
        db_agent = db.query(Agent).filter(
            and_(
                Agent.id == agent_uuid,
                Agent.organization_id == organization_id
            )
        ).first()
    except ValueError:
        db_agent = db.query(Agent).filter(
            and_(
                Agent.agent_id == agent_id,
                Agent.organization_id == organization_id
            )
        ).first()

    if not db_agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    dependencies = get_agent_dependencies(db, organization_id, db_agent.id)
    return {
        "agent_id": str(db_agent.id),
        "agent_name": db_agent.name,
        "dependencies": dependencies,
        "can_delete_without_force": len(dependencies) == 0,
    }

