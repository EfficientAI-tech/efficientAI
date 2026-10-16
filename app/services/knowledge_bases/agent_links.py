"""Sync agent ↔ knowledge base attachments."""

from __future__ import annotations

from typing import Iterable, List
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import Agent, AgentKnowledgeBase, KnowledgeBase


def get_agent_knowledge_base_ids(db: Session, *, agent_id: UUID) -> List[UUID]:
    rows = (
        db.query(AgentKnowledgeBase.knowledge_base_id)
        .filter(AgentKnowledgeBase.agent_id == agent_id)
        .all()
    )
    return [row[0] for row in rows]


def replace_agent_knowledge_bases(
    db: Session,
    *,
    agent: Agent,
    organization_id: UUID,
    workspace_id: UUID,
    knowledge_base_ids: Iterable[UUID],
) -> None:
    desired = list(dict.fromkeys(knowledge_base_ids))
    if desired:
        valid = (
            db.query(KnowledgeBase.id)
            .filter(
                KnowledgeBase.id.in_(desired),
                KnowledgeBase.organization_id == organization_id,
                KnowledgeBase.workspace_id == workspace_id,
            )
            .all()
        )
        valid_ids = {row[0] for row in valid}
        missing = [str(kb_id) for kb_id in desired if kb_id not in valid_ids]
        if missing:
            raise ValueError(f"Knowledge base(s) not found in workspace: {', '.join(missing)}")
    db.query(AgentKnowledgeBase).filter(AgentKnowledgeBase.agent_id == agent.id).delete()
    for kb_id in desired:
        db.add(
            AgentKnowledgeBase(
                agent_id=agent.id,
                knowledge_base_id=kb_id,
                organization_id=organization_id,
                workspace_id=workspace_id,
            )
        )
