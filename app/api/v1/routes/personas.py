"""
Personas API Routes
Complete CRUD operations for test personas
"""
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from typing import List, Optional
from uuid import UUID

from app.dependencies import get_db, get_organization_id
from app.models.database import Persona
from app.models.schemas import (
    PersonaCreate, PersonaUpdate, PersonaResponse, PersonaCloneRequest
)

router = APIRouter(prefix="/personas", tags=["personas"])


@router.post("", response_model=PersonaResponse, status_code=status.HTTP_201_CREATED)
async def create_persona(
    persona: PersonaCreate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Create a new persona"""
    try:
        db_persona = Persona(
            organization_id=organization_id,
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
    except IntegrityError as e:
        db.rollback()
        if "foreign key constraint" in str(e.orig).lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid organization_id: {organization_id}"
            )
        elif "unique constraint" in str(e.orig).lower() or "duplicate key" in str(e.orig).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A persona with this name already exists"
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Database constraint violation"
        )
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error creating persona: {str(e)}"
        )


@router.get("", response_model=List[PersonaResponse])
async def list_personas(
    skip: int = 0,
    limit: int = 100,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Get list of all personas for the organization"""
    try:
        personas = db.query(Persona).filter(
            Persona.organization_id == organization_id
        ).offset(skip).limit(limit).all()
        return personas
    except SQLAlchemyError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error retrieving personas: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error retrieving personas: {str(e)}"
        )


@router.get("/{persona_id}", response_model=PersonaResponse)
async def get_persona(
    persona_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Get a specific persona by ID"""
    try:
        persona = db.query(Persona).filter(
            Persona.id == persona_id,
            Persona.organization_id == organization_id
        ).first()
        if not persona:
            raise HTTPException(status_code=404, detail=f"Persona {persona_id} not found")
        return persona
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error retrieving persona: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error retrieving persona: {str(e)}"
        )


@router.put("/{persona_id}", response_model=PersonaResponse)
async def update_persona(
    persona_id: UUID,
    persona_update: PersonaUpdate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Update an existing persona"""
    try:
        db_persona = db.query(Persona).filter(
            Persona.id == persona_id,
            Persona.organization_id == organization_id
        ).first()
        if not db_persona:
            raise HTTPException(status_code=404, detail=f"Persona {persona_id} not found")
        
        update_data = persona_update.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_persona, field, value)
        
        db.commit()
        db.refresh(db_persona)
        return db_persona
    except HTTPException:
        raise
    except IntegrityError as e:
        db.rollback()
        if "unique constraint" in str(e.orig).lower() or "duplicate key" in str(e.orig).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A persona with this name already exists"
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Database constraint violation"
        )
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error updating persona: {str(e)}"
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error updating persona: {str(e)}"
        )


@router.delete("/{persona_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_persona(
    persona_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Delete a persona"""
    try:
        db_persona = db.query(Persona).filter(
            Persona.id == persona_id,
            Persona.organization_id == organization_id
        ).first()
        if not db_persona:
            raise HTTPException(status_code=404, detail=f"Persona {persona_id} not found")
        
        db.delete(db_persona)
        db.commit()
        return None
    except HTTPException:
        raise
    except IntegrityError as e:
        db.rollback()
        if "foreign key constraint" in str(e.orig).lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete persona: it is being used by other records"
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Database constraint violation"
        )
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error deleting persona: {str(e)}"
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error deleting persona: {str(e)}"
        )


@router.post("/{persona_id}/clone", response_model=PersonaResponse, status_code=status.HTTP_201_CREATED)
async def clone_persona(
    persona_id: UUID,
    clone_request: PersonaCloneRequest,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Clone an existing persona to create a new one"""
    try:
        source_persona = db.query(Persona).filter(
            Persona.id == persona_id,
            Persona.organization_id == organization_id
        ).first()
        if not source_persona:
            raise HTTPException(status_code=404, detail=f"Persona {persona_id} not found")
        
        # Create new persona with same attributes
        new_persona = Persona(
            organization_id=organization_id,
            name=clone_request.name if clone_request.name else f"{source_persona.name} (Copy)",
            language=source_persona.language,
            accent=source_persona.accent,
            gender=source_persona.gender,
            background_noise=source_persona.background_noise
        )
        db.add(new_persona)
        db.commit()
        db.refresh(new_persona)
        return new_persona
    except HTTPException:
        raise
    except IntegrityError as e:
        db.rollback()
        if "foreign key constraint" in str(e.orig).lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid organization_id: {organization_id}"
            )
        elif "unique constraint" in str(e.orig).lower() or "duplicate key" in str(e.orig).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A persona with this name already exists"
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Database constraint violation"
        )
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error cloning persona: {str(e)}"
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error cloning persona: {str(e)}"
        )


# ============================================
# SEED DATA (Helper for demo)
# ============================================

@router.post("/seed-data", status_code=status.HTTP_201_CREATED)
async def seed_demo_data(
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Seed database with example personas and scenarios for the organization"""
    from app.models.database import Scenario
    
    try:
        # Example personas
        personas_data = [
            {"name": "Grumpy Old Man", "language": "en", "accent": "american", "gender": "male", "background_noise": "none"},
            {"name": "Confused Senior", "language": "en", "accent": "american", "gender": "female", "background_noise": "home"},
            {"name": "Busy Professional", "language": "en", "accent": "american", "gender": "neutral", "background_noise": "office"},
            {"name": "Friendly Customer", "language": "en", "accent": "american", "gender": "female", "background_noise": "none"},
            {"name": "Angry Caller", "language": "en", "accent": "american", "gender": "male", "background_noise": "street"},
        ]
        
        # Check if personas already exist to avoid duplicates
        existing_persona_names = {p.name for p in db.query(Persona).filter(
            Persona.organization_id == organization_id,
            Persona.name.in_([p["name"] for p in personas_data])
        ).all()}
        
        personas_created = 0
        for persona_data in personas_data:
            if persona_data["name"] not in existing_persona_names:
                persona = Persona(organization_id=organization_id, **persona_data)
                db.add(persona)
                personas_created += 1
        
        # Example scenarios
        scenarios_data = [
            {"name": "Cancel Subscription", "description": "Customer wants to cancel", "required_info": {"account_number": "string", "reason": "string"}},
            {"name": "Check Balance", "description": "Check account balance", "required_info": {"account_number": "string"}},
            {"name": "Technical Support", "description": "Technical issue", "required_info": {"product": "string", "issue": "string"}},
            {"name": "Make Complaint", "description": "File a complaint", "required_info": {"complaint_type": "string"}},
            {"name": "Product Inquiry", "description": "Ask about product", "required_info": {"product_category": "string"}},
        ]
        
        # Check if scenarios already exist to avoid duplicates
        existing_scenario_names = {s.name for s in db.query(Scenario).filter(
            Scenario.organization_id == organization_id,
            Scenario.name.in_([s["name"] for s in scenarios_data])
        ).all()}
        
        scenarios_created = 0
        for scenario_data in scenarios_data:
            if scenario_data["name"] not in existing_scenario_names:
                scenario = Scenario(organization_id=organization_id, **scenario_data)
                db.add(scenario)
                scenarios_created += 1
        
        db.commit()
        
        return {
            "message": "Demo data created",
            "personas_created": personas_created,
            "personas_skipped": len(personas_data) - personas_created,
            "scenarios_created": scenarios_created,
            "scenarios_skipped": len(scenarios_data) - scenarios_created
        }
    except IntegrityError as e:
        db.rollback()
        if "foreign key constraint" in str(e.orig).lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid organization_id: {organization_id}"
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Database constraint violation while seeding data"
        )
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error seeding demo data: {str(e)}"
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error seeding demo data: {str(e)}"
        )

