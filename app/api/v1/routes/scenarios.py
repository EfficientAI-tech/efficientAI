"""
Scenarios API Routes
Complete CRUD operations for test scenarios
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID

from app.dependencies import get_db, get_organization_id
from app.models.database import Scenario
from app.models.schemas import (
    ScenarioCreate, ScenarioUpdate, ScenarioResponse
)

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


@router.post("", response_model=ScenarioResponse, status_code=status.HTTP_201_CREATED)
async def create_scenario(
    scenario: ScenarioCreate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Create a new scenario"""
    db_scenario = Scenario(
        organization_id=organization_id,
        name=scenario.name,
        description=scenario.description,
        required_info=scenario.required_info
    )
    db.add(db_scenario)
    db.commit()
    db.refresh(db_scenario)
    return db_scenario


@router.get("", response_model=List[ScenarioResponse])
async def list_scenarios(
    skip: int = 0,
    limit: int = 100,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Get list of all scenarios for the organization"""
    scenarios = db.query(Scenario).filter(
        Scenario.organization_id == organization_id
    ).offset(skip).limit(limit).all()
    return scenarios


@router.get("/{scenario_id}", response_model=ScenarioResponse)
async def get_scenario(
    scenario_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Get a specific scenario by ID"""
    scenario = db.query(Scenario).filter(
        Scenario.id == scenario_id,
        Scenario.organization_id == organization_id
    ).first()
    if not scenario:
        raise HTTPException(status_code=404, detail=f"Scenario {scenario_id} not found")
    return scenario


@router.put("/{scenario_id}", response_model=ScenarioResponse)
async def update_scenario(
    scenario_id: UUID,
    scenario_update: ScenarioUpdate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Update an existing scenario"""
    db_scenario = db.query(Scenario).filter(
        Scenario.id == scenario_id,
        Scenario.organization_id == organization_id
    ).first()
    if not db_scenario:
        raise HTTPException(status_code=404, detail=f"Scenario {scenario_id} not found")
    
    update_data = scenario_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_scenario, field, value)
    
    db.commit()
    db.refresh(db_scenario)
    return db_scenario


@router.delete("/{scenario_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scenario(
    scenario_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Delete a scenario"""
    db_scenario = db.query(Scenario).filter(
        Scenario.id == scenario_id,
        Scenario.organization_id == organization_id
    ).first()
    if not db_scenario:
        raise HTTPException(status_code=404, detail=f"Scenario {scenario_id} not found")
    
    db.delete(db_scenario)
    db.commit()
    return None

