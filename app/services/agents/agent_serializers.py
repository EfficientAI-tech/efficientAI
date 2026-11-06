"""Agent API response helpers."""

from __future__ import annotations

from typing import Iterable, List

from sqlalchemy.orm import Session

from app.models.database import Agent
from app.models.schemas import AgentResponse
from app.services.knowledge_bases.agent_links import KB_ROLE_TEST, get_agent_knowledge_base_ids


def agent_to_response(db: Session, agent: Agent) -> AgentResponse:
    return AgentResponse.model_validate(agent).model_copy(
        update={
            "knowledge_base_ids": get_agent_knowledge_base_ids(db, agent_id=agent.id),
            "test_knowledge_base_ids": get_agent_knowledge_base_ids(
                db, agent_id=agent.id, role=KB_ROLE_TEST
            ),
        }
    )


def agents_to_responses(db: Session, agents: Iterable[Agent]) -> List[AgentResponse]:
    return [agent_to_response(db, agent) for agent in agents]
