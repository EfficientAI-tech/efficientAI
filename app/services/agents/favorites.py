"""Per-user agent stars. A favorite belongs to one user, not the workspace."""

from __future__ import annotations

from typing import Iterable, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import UserAgentFavorite
from app.models.schemas import AgentResponse


def favorite_agent_ids(db: Session, *, user_id: Optional[UUID], agent_ids: Iterable[UUID]) -> set[UUID]:
    ids = list(agent_ids)
    if user_id is None or not ids:
        return set()
    rows = (
        db.query(UserAgentFavorite.agent_id)
        .filter(UserAgentFavorite.user_id == user_id, UserAgentFavorite.agent_id.in_(ids))
        .all()
    )
    return {row[0] for row in rows}


def apply_favorite(response: AgentResponse, *, is_favorite: bool) -> AgentResponse:
    return response.model_copy(update={"is_favorite": is_favorite})


def set_favorite(
    db: Session,
    *,
    user_id: UUID,
    agent_id: UUID,
    organization_id: UUID,
    workspace_id: UUID,
    favorite: bool,
) -> bool:
    existing = (
        db.query(UserAgentFavorite)
        .filter(UserAgentFavorite.user_id == user_id, UserAgentFavorite.agent_id == agent_id)
        .first()
    )
    if favorite and existing is None:
        db.add(
            UserAgentFavorite(
                user_id=user_id,
                agent_id=agent_id,
                organization_id=organization_id,
                workspace_id=workspace_id,
            )
        )
    elif not favorite and existing is not None:
        db.delete(existing)
    db.commit()
    return favorite
