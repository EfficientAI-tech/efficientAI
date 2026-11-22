"""Shared helpers for action kinds.

Action kinds call existing route handlers directly so the same validation and
business rules apply as in the UI. Two things FastAPI normally does are lost
when you call a handler as a function, and are handled here instead:

* router-level dependencies (capability checks, enterprise gates) don't run, so
  each kind declares its capability and calls ``require_feature`` itself;
* ``Query(...)``/``Body(...)`` defaults are FieldInfo objects (truthy!), so
  every such parameter must be passed explicitly.
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.auth.principal import AuthMethod, Principal
from app.models.database import Agent, CallImport, CallImportEvaluation, Persona, Scenario
from app.services.copilot.actions.base import ActionContext


def principal_for(ctx: ActionContext) -> Principal:
    return Principal(
        organization_id=ctx.organization_id,
        auth_method=AuthMethod.LOCAL_PASSWORD,
        user_id=ctx.user_id,
    )


def require_feature(ctx: ActionContext, feature: str) -> None:
    from app.core.license import is_feature_enabled

    if not is_feature_enabled(feature, ctx.organization_id):
        raise HTTPException(
            status_code=403,
            detail=f"'{feature}' is an EfficientAI Enterprise feature and isn't enabled for this organization.",
        )


def response_status(response: Any) -> Optional[int]:
    return getattr(response, "status_code", None)


def _scoped(db: Session, model: Any, org: UUID, ws: UUID, row_id: UUID) -> Any:
    return (
        db.query(model)
        .filter(model.id == row_id, model.organization_id == org, model.workspace_id == ws)
        .first()
    )


def agent_or_error(db: Session, org: UUID, ws: UUID, agent_id: UUID) -> Agent:
    agent = _scoped(db, Agent, org, ws, agent_id)
    if agent is None:
        raise ValueError("That agent isn't in this workspace.")
    return agent


def persona_or_error(db: Session, org: UUID, ws: UUID, persona_id: UUID) -> Persona:
    row = _scoped(db, Persona, org, ws, persona_id)
    if row is None:
        raise ValueError("That persona isn't in this workspace.")
    return row


def scenario_or_error(db: Session, org: UUID, ws: UUID, scenario_id: UUID) -> Scenario:
    row = _scoped(db, Scenario, org, ws, scenario_id)
    if row is None:
        raise ValueError("That scenario isn't in this workspace.")
    return row


def import_or_error(db: Session, org: UUID, ws: UUID, call_import_id: UUID) -> CallImport:
    row = _scoped(db, CallImport, org, ws, call_import_id)
    if row is None:
        raise ValueError("That import isn't in this workspace.")
    return row


def import_evaluation_or_error(db: Session, org: UUID, ws: UUID, evaluation_id: UUID) -> CallImportEvaluation:
    row = _scoped(db, CallImportEvaluation, org, ws, evaluation_id)
    if row is None:
        raise ValueError("That import evaluation isn't in this workspace.")
    return row


def enum_value(value: Any) -> Any:
    return getattr(value, "value", value)
