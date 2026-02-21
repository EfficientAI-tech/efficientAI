"""
Scenarios API Routes
Complete CRUD operations for test scenarios
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID

from app.dependencies import get_db, get_organization_id
from app.models.database import Scenario, Evaluator, EvaluatorResult, TestAgentConversation
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


@router.delete("/{scenario_id}")
async def delete_scenario(
    scenario_id: UUID,
    force: bool = Query(False, description="Force delete with all dependent records"),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Delete a scenario. Returns 409 if dependent records exist unless force=true."""
    db_scenario = db.query(Scenario).filter(
        Scenario.id == scenario_id,
        Scenario.organization_id == organization_id
    ).first()
    if not db_scenario:
        raise HTTPException(status_code=404, detail=f"Scenario {scenario_id} not found")

    evaluators_count = db.query(Evaluator).filter(
        Evaluator.scenario_id == scenario_id,
        Evaluator.organization_id == organization_id,
    ).count()

    evaluator_results_count = db.query(EvaluatorResult).filter(
        EvaluatorResult.scenario_id == scenario_id,
        EvaluatorResult.organization_id == organization_id,
    ).count()

    test_conversations_count = db.query(TestAgentConversation).filter(
        TestAgentConversation.scenario_id == scenario_id,
        TestAgentConversation.organization_id == organization_id,
    ).count()

    dependencies = {}
    if evaluators_count > 0:
        dependencies["evaluators"] = evaluators_count
    if evaluator_results_count > 0:
        dependencies["evaluator_results"] = evaluator_results_count
    if test_conversations_count > 0:
        dependencies["test_conversations"] = test_conversations_count

    if dependencies and not force:
        parts = []
        if evaluators_count > 0:
            parts.append(f"{evaluators_count} evaluator(s)")
        if evaluator_results_count > 0:
            parts.append(f"{evaluator_results_count} evaluator result(s)")
        if test_conversations_count > 0:
            parts.append(f"{test_conversations_count} test conversation(s)")

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": f"Cannot delete scenario. It is referenced by: {', '.join(parts)}.",
                "dependencies": dependencies,
                "hint": "Use force=true to delete this scenario and all its dependent records.",
            },
        )

    if dependencies:
        db.query(EvaluatorResult).filter(
            EvaluatorResult.scenario_id == scenario_id,
            EvaluatorResult.organization_id == organization_id,
        ).delete(synchronize_session=False)

        db.query(Evaluator).filter(
            Evaluator.scenario_id == scenario_id,
            Evaluator.organization_id == organization_id,
        ).delete(synchronize_session=False)

        db.query(TestAgentConversation).filter(
            TestAgentConversation.scenario_id == scenario_id,
            TestAgentConversation.organization_id == organization_id,
        ).delete(synchronize_session=False)

    db.delete(db_scenario)
    db.commit()

    if dependencies:
        return JSONResponse(
            status_code=200,
            content={
                "message": "Scenario and all dependent records deleted successfully.",
                "deleted": dependencies,
            },
        )

    return JSONResponse(status_code=204, content=None)

