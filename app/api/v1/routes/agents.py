"""
Agents API Routes
Complete CRUD operations for test agents
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID
import random

from app.dependencies import get_db, get_organization_id
from app.models.database import Agent, ConversationEvaluation, TestAgentConversation, VoiceBundle, AIProvider, CallMediumEnum
from sqlalchemy import and_
from app.models.schemas import (
    AgentCreate, AgentUpdate, AgentResponse, CallMediumEnum as CallMediumEnumSchema
)

router = APIRouter(prefix="/agents", tags=["agents"])


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
    
    # Validate voice_bundle_id or ai_provider_id exists and belongs to organization
    if agent.voice_bundle_id:
        voice_bundle = db.query(VoiceBundle).filter(
            and_(
                VoiceBundle.id == agent.voice_bundle_id,
                VoiceBundle.organization_id == organization_id
            )
        ).first()
        if not voice_bundle:
            raise HTTPException(status_code=404, detail="Voice bundle not found")
    
    if agent.ai_provider_id:
        ai_provider = db.query(AIProvider).filter(
            and_(
                AIProvider.id == agent.ai_provider_id,
                AIProvider.organization_id == organization_id
            )
        ).first()
        if not ai_provider:
            raise HTTPException(status_code=404, detail="AI Provider not found")
    
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
        ai_provider_id=agent.ai_provider_id
    )
    db.add(db_agent)
    db.commit()
    db.refresh(db_agent)
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
    
    # Validate voice_bundle_id or ai_provider_id if provided
    if agent_update.voice_bundle_id:
        voice_bundle = db.query(VoiceBundle).filter(
            and_(
                VoiceBundle.id == agent_update.voice_bundle_id,
                VoiceBundle.organization_id == organization_id
            )
        ).first()
        if not voice_bundle:
            raise HTTPException(status_code=404, detail="Voice bundle not found")
    
    if agent_update.ai_provider_id:
        ai_provider = db.query(AIProvider).filter(
            and_(
                AIProvider.id == agent_update.ai_provider_id,
                AIProvider.organization_id == organization_id
            )
        ).first()
        if not ai_provider:
            raise HTTPException(status_code=404, detail="AI Provider not found")
    
    update_data = agent_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_agent, field, value)
    
    db.commit()
    db.refresh(db_agent)
    return db_agent


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: str,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Delete an agent by ID (UUID) or agent_id (6-digit)."""
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
    
    # Use the UUID for checking references
    agent_uuid = db_agent.id
    
    # Check for references in ConversationEvaluation (Metrics Dashboard)
    conversation_evaluations = db.query(ConversationEvaluation).filter(
        ConversationEvaluation.agent_id == agent_id,
        ConversationEvaluation.organization_id == organization_id
    ).count()
    
    # Check for references in TestAgentConversation
    test_conversations = db.query(TestAgentConversation).filter(
        TestAgentConversation.agent_id == agent_id,
        TestAgentConversation.organization_id == organization_id
    ).count()
    
    # Build error message if agent is referenced
    references = []
    if conversation_evaluations > 0:
        references.append(f"{conversation_evaluations} conversation evaluation(s) in Metrics Dashboard")
    if test_conversations > 0:
        references.append(f"{test_conversations} test conversation(s)")
    
    if references:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete agent. It is currently being used by: {', '.join(references)}. Please remove these references before deleting the agent."
        )
    
    db.delete(db_agent)
    db.commit()
    return None

