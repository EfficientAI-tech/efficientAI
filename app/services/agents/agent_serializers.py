"""Agent API response helpers."""

from __future__ import annotations

from typing import Iterable, List

from sqlalchemy.orm import Session

from app.models.database import Agent
from app.models.schemas import AgentResponse
from app.services.knowledge_bases.agent_links import get_agent_knowledge_base_ids


def agent_to_response(db: Session, agent: Agent) -> AgentResponse:
    kb_ids = get_agent_knowledge_base_ids(db, agent_id=agent.id)
    return AgentResponse.model_validate(agent).model_copy(update={"knowledge_base_ids": kb_ids})


def agents_to_responses(db: Session, agents: Iterable[Agent]) -> List[AgentResponse]:
    return [agent_to_response(db, agent) for agent in agents]
