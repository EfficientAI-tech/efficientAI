"""
Personas API Routes
Complete CRUD operations for test personas
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID

from app.dependencies import get_db
from app.models.database import Persona
from app.models.schemas import (
    PersonaCreate, PersonaUpdate, PersonaResponse
)

router = APIRouter(prefix="/personas", tags=["personas"])


@router.post("", response_model=PersonaResponse, status_code=status.HTTP_201_CREATED)
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


@router.get("", response_model=List[PersonaResponse])
async def list_personas(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """Get list of all personas"""
    personas = db.query(Persona).offset(skip).limit(limit).all()
    return personas


@router.get("/{persona_id}", response_model=PersonaResponse)
async def get_persona(persona_id: UUID, db: Session = Depends(get_db)):
    """Get a specific persona by ID"""
    persona = db.query(Persona).filter(Persona.id == persona_id).first()
    if not persona:
        raise HTTPException(status_code=404, detail=f"Persona {persona_id} not found")
    return persona


@router.put("/{persona_id}", response_model=PersonaResponse)
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


@router.delete("/{persona_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_persona(persona_id: UUID, db: Session = Depends(get_db)):
    """Delete a persona"""
    db_persona = db.query(Persona).filter(Persona.id == persona_id).first()
    if not db_persona:
        raise HTTPException(status_code=404, detail=f"Persona {persona_id} not found")
    
    db.delete(db_persona)
    db.commit()
    return None


# ============================================
# SEED DATA (Helper for demo)
# ============================================

@router.post("/seed-data", status_code=status.HTTP_201_CREATED)
async def seed_demo_data(db: Session = Depends(get_db)):
    """Seed database with example personas and scenarios"""
    from app.models.database import Scenario
    
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

