"""Evaluator routes."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import and_
from uuid import UUID
import random
from typing import List

from app.database import get_db
from app.dependencies import get_organization_id, get_api_key
from app.models.database import Evaluator, Agent, Persona, Scenario
from app.models.schemas import (
    EvaluatorCreate,
    EvaluatorUpdate,
    EvaluatorResponse,
    EvaluatorBulkCreate,
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


@router.post("", response_model=EvaluatorResponse, status_code=201)
def create_evaluator(
    evaluator_data: EvaluatorCreate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Create a new evaluator."""
    # Verify agent exists and belongs to organization
    agent = db.query(Agent).filter(
        and_(Agent.id == evaluator_data.agent_id, Agent.organization_id == organization_id)
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Verify persona exists and belongs to organization
    persona = db.query(Persona).filter(
        and_(Persona.id == evaluator_data.persona_id, Persona.organization_id == organization_id)
    ).first()
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")

    # Verify scenario exists and belongs to organization
    scenario = db.query(Scenario).filter(
        and_(Scenario.id == evaluator_data.scenario_id, Scenario.organization_id == organization_id)
    ).first()
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")

    # Generate unique 6-digit ID
    evaluator_id = generate_unique_evaluator_id(db)

    # Create evaluator
    evaluator = Evaluator(
        evaluator_id=evaluator_id,
        organization_id=organization_id,
        agent_id=evaluator_data.agent_id,
        persona_id=evaluator_data.persona_id,
        scenario_id=evaluator_data.scenario_id,
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

    db.commit()
    db.refresh(evaluator)

    return evaluator


@router.delete("/{evaluator_id}", status_code=204)
def delete_evaluator(
    evaluator_id: str,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Delete an evaluator."""
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

    db.delete(evaluator)
    db.commit()

    return None

