"""
vaiops - Voice AI Ops API Routes
Complete CRUD operations for agents, personas, and scenarios
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID

from app.dependencies import get_db
from app.models.database import Agent, Persona, Scenario
from app.models.schemas import (
    AgentCreate, AgentUpdate, AgentResponse,
    PersonaCreate, PersonaUpdate, PersonaResponse,
    ScenarioCreate, ScenarioUpdate, ScenarioResponse
)

router = APIRouter(prefix="/vaiops", tags=["vaiops"])


# ============================================
# AGENT ENDPOINTS
# ============================================

@router.post("/agents", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(agent: AgentCreate, db: Session = Depends(get_db)):
    """Create a new test agent"""
    db_agent = Agent(
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


@router.get("/agents", response_model=List[AgentResponse])
async def list_agents(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """Get list of all agents"""
    agents = db.query(Agent).offset(skip).limit(limit).all()
    return agents


@router.get("/agents/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: UUID, db: Session = Depends(get_db)):
    """Get a specific agent by ID"""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    return agent


@router.put("/agents/{agent_id}", response_model=AgentResponse)
async def update_agent(agent_id: UUID, agent_update: AgentUpdate, db: Session = Depends(get_db)):
    """Update an existing agent"""
    db_agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not db_agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    
    update_data = agent_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_agent, field, value)
    
    db.commit()
    db.refresh(db_agent)
    return db_agent


@router.delete("/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: UUID, db: Session = Depends(get_db)):
    """Delete an agent"""
    db_agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not db_agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    
    db.delete(db_agent)
    db.commit()
    return None


# ============================================
# PERSONA ENDPOINTS
# ============================================

@router.post("/personas", response_model=PersonaResponse, status_code=status.HTTP_201_CREATED)
async def create_persona(persona: PersonaCreate, db: Session = Depends(get_db)):
    """Create a new persona"""
    db_persona = Persona(
        name=persona.name,
        language=persona.language,
        accent=persona.accent,
        gender=persona.gender,
        background_noise=persona.background_noise
    )
    db.add(db_persona)
    db.commit()
    db.refresh(db_persona)
    return db_persona


@router.get("/personas", response_model=List[PersonaResponse])
async def list_personas(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """Get list of all personas"""
    personas = db.query(Persona).offset(skip).limit(limit).all()
    return personas


@router.get("/personas/{persona_id}", response_model=PersonaResponse)
async def get_persona(persona_id: UUID, db: Session = Depends(get_db)):
    """Get a specific persona by ID"""
    persona = db.query(Persona).filter(Persona.id == persona_id).first()
    if not persona:
        raise HTTPException(status_code=404, detail=f"Persona {persona_id} not found")
    return persona


@router.put("/personas/{persona_id}", response_model=PersonaResponse)
async def update_persona(persona_id: UUID, persona_update: PersonaUpdate, db: Session = Depends(get_db)):
    """Update an existing persona"""
    db_persona = db.query(Persona).filter(Persona.id == persona_id).first()
    if not db_persona:
        raise HTTPException(status_code=404, detail=f"Persona {persona_id} not found")
    
    update_data = persona_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_persona, field, value)
    
    db.commit()
    db.refresh(db_persona)
    return db_persona


@router.delete("/personas/{persona_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_persona(persona_id: UUID, db: Session = Depends(get_db)):
    """Delete a persona"""
    db_persona = db.query(Persona).filter(Persona.id == persona_id).first()
    if not db_persona:
        raise HTTPException(status_code=404, detail=f"Persona {persona_id} not found")
    
    db.delete(db_persona)
    db.commit()
    return None


# ============================================
# SCENARIO ENDPOINTS
# ============================================

@router.post("/scenarios", response_model=ScenarioResponse, status_code=status.HTTP_201_CREATED)
async def create_scenario(scenario: ScenarioCreate, db: Session = Depends(get_db)):
    """Create a new scenario"""
    db_scenario = Scenario(
        name=scenario.name,
        description=scenario.description,
        required_info=scenario.required_info
    )
    db.add(db_scenario)
    db.commit()
    db.refresh(db_scenario)
    return db_scenario


@router.get("/scenarios", response_model=List[ScenarioResponse])
async def list_scenarios(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """Get list of all scenarios"""
    scenarios = db.query(Scenario).offset(skip).limit(limit).all()
    return scenarios


@router.get("/scenarios/{scenario_id}", response_model=ScenarioResponse)
async def get_scenario(scenario_id: UUID, db: Session = Depends(get_db)):
    """Get a specific scenario by ID"""
    scenario = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    if not scenario:
        raise HTTPException(status_code=404, detail=f"Scenario {scenario_id} not found")
    return scenario


@router.put("/scenarios/{scenario_id}", response_model=ScenarioResponse)
async def update_scenario(scenario_id: UUID, scenario_update: ScenarioUpdate, db: Session = Depends(get_db)):
    """Update an existing scenario"""
    db_scenario = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    if not db_scenario:
        raise HTTPException(status_code=404, detail=f"Scenario {scenario_id} not found")
    
    update_data = scenario_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_scenario, field, value)
    
    db.commit()
    db.refresh(db_scenario)
    return db_scenario


@router.delete("/scenarios/{scenario_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scenario(scenario_id: UUID, db: Session = Depends(get_db)):
    """Delete a scenario"""
    db_scenario = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    if not db_scenario:
        raise HTTPException(status_code=404, detail=f"Scenario {scenario_id} not found")
    
    db.delete(db_scenario)
    db.commit()
    return None


# ============================================
# SEED DATA (Helper for demo)
# ============================================

@router.post("/seed-data", status_code=status.HTTP_201_CREATED)
async def seed_demo_data(db: Session = Depends(get_db)):
    """Seed database with example personas and scenarios"""
    
    # Example personas
    personas_data = [
        {"name": "Grumpy Old Man", "language": "en", "accent": "american", "gender": "male", "background_noise": "none"},
        {"name": "Confused Senior", "language": "en", "accent": "american", "gender": "female", "background_noise": "home"},
        {"name": "Busy Professional", "language": "en", "accent": "american", "gender": "neutral", "background_noise": "office"},
        {"name": "Friendly Customer", "language": "en", "accent": "american", "gender": "female", "background_noise": "none"},
        {"name": "Angry Caller", "language": "en", "accent": "american", "gender": "male", "background_noise": "street"},
    ]
    
    for persona_data in personas_data:
        persona = Persona(**persona_data)
        db.add(persona)
    
    # Example scenarios
    scenarios_data = [
        {"name": "Cancel Subscription", "description": "Customer wants to cancel", "required_info": {"account_number": "string", "reason": "string"}},
        {"name": "Check Balance", "description": "Check account balance", "required_info": {"account_number": "string"}},
        {"name": "Technical Support", "description": "Technical issue", "required_info": {"product": "string", "issue": "string"}},
        {"name": "Make Complaint", "description": "File a complaint", "required_info": {"complaint_type": "string"}},
        {"name": "Product Inquiry", "description": "Ask about product", "required_info": {"product_category": "string"}},
    ]
    
    for scenario_data in scenarios_data:
        scenario = Scenario(**scenario_data)
        db.add(scenario)
    
    db.commit()
    
    return {"message": "Demo data created", "personas": len(personas_data), "scenarios": len(scenarios_data)}