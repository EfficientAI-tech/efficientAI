"""
Agents API Routes
Complete CRUD operations for test agents
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID

from app.dependencies import get_db, get_organization_id
from app.models.database import Agent
from app.models.schemas import (
    AgentCreate, AgentUpdate, AgentResponse
)

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED, operation_id="createAgent")
async def create_agent(
    agent: AgentCreate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Create a new test agent"""
    db_agent = Agent(
        organization_id=organization_id,
        name=agent.name,
        phone_number=agent.phone_number,
        language=agent.language,
        description=agent.description,
        call_type=agent.call_type
    )
    db.add(db_agent)
    db.commit()
    db.refresh(db_agent)
    return db_agent


@router.get("", response_model=List[AgentResponse], operation_id="listAgents")
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
    agent_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Get a specific agent by ID"""
    agent = db.query(Agent).filter(
        Agent.id == agent_id,
        Agent.organization_id == organization_id
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    return agent


@router.put("/{agent_id}", response_model=AgentResponse, operation_id="updateAgent")
async def update_agent(
    agent_id: UUID,
    agent_update: AgentUpdate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Update an existing agent"""
    db_agent = db.query(Agent).filter(
        Agent.id == agent_id,
        Agent.organization_id == organization_id
    ).first()
    if not db_agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    
    update_data = agent_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_agent, field, value)
    
    db.commit()
    db.refresh(db_agent)
    return db_agent


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT, operation_id="deleteAgent")
async def delete_agent(
    agent_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Delete an agent"""
    db_agent = db.query(Agent).filter(
        Agent.id == agent_id,
        Agent.organization_id == organization_id
    ).first()
    if not db_agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    
    db.delete(db_agent)
    db.commit()
    return None

