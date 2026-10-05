"""Default persona for text-chat evaluator suites (scenario-driven customer sim)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import Persona
from app.models.enums import GenderEnum, SimulationMediumEnum

DEFAULT_CHAT_EVAL_PERSONA_NAME = "Chat simulation customer"


def ensure_default_chat_eval_persona(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
) -> UUID:
    existing = (
        db.query(Persona)
        .filter(
            Persona.organization_id == organization_id,
            Persona.workspace_id == workspace_id,
            Persona.simulation_medium == SimulationMediumEnum.TEXT.value,
            Persona.name == DEFAULT_CHAT_EVAL_PERSONA_NAME,
        )
        .first()
    )
    if existing:
        return existing.id

    persona = Persona(
        organization_id=organization_id,
        workspace_id=workspace_id,
        name=DEFAULT_CHAT_EVAL_PERSONA_NAME,
        simulation_medium=SimulationMediumEnum.TEXT.value,
        gender=GenderEnum.NEUTRAL.value,
        description=(
            "Built-in simulated customer for text chat evaluator runs. "
            "Use scenarios to define goals; the agent production prompt defines the bot under test."
        ),
        background_noise_source="none",
    )
    db.add(persona)
    db.flush()
    return persona.id
