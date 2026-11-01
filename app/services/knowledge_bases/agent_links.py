"""Sync agent ↔ knowledge base attachments (separately for the production and test sides)."""

from __future__ import annotations

from typing import Iterable, List
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import Agent, AgentKnowledgeBase, KnowledgeBase

KB_ROLE_PRODUCTION = "production"
KB_ROLE_TEST = "test"
KB_ROLES = (KB_ROLE_PRODUCTION, KB_ROLE_TEST)


def get_agent_knowledge_base_ids(
    db: Session, *, agent_id: UUID, role: str = KB_ROLE_PRODUCTION
) -> List[UUID]:
    rows = (
        db.query(AgentKnowledgeBase.knowledge_base_id)
        .filter(AgentKnowledgeBase.agent_id == agent_id, AgentKnowledgeBase.role == role)
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
    role: str = KB_ROLE_PRODUCTION,
) -> None:
    if role not in KB_ROLES:
        raise ValueError(f"Unknown knowledge base role: {role}")
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
    db.query(AgentKnowledgeBase).filter(
        AgentKnowledgeBase.agent_id == agent.id, AgentKnowledgeBase.role == role
    ).delete()
    for kb_id in desired:
        db.add(
            AgentKnowledgeBase(
                agent_id=agent.id,
                knowledge_base_id=kb_id,
                role=role,
                organization_id=organization_id,
                workspace_id=workspace_id,
            )
        )
