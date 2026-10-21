"""Tool-aware chat completion for internal production simulation."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.enums import ModelProvider
from app.services.knowledge_bases.agent_links import KB_ROLE_PRODUCTION, KB_ROLE_TEST
from app.services.knowledge_bases.prompt import append_knowledge_base_instructions
from app.services.tools.loop import run_tool_loop
from app.services.tools.providers.knowledge_base import KnowledgeBaseToolProvider
from app.services.tools.toolset import Toolset

MAX_TOOL_ROUNDS = 3


def with_knowledge_base_instructions(
    messages: List[Dict[str, Any]], *, simulated_caller: bool = False
) -> List[Dict[str, Any]]:
    working = list(messages)
    if working and working[0].get("role") == "system":
        working[0] = {
            "role": "system",
            "content": append_knowledge_base_instructions(
                working[0].get("content") or "", simulated_caller=simulated_caller
            ),
        }
    return working


def generate_production_reply_with_knowledge_tools(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    agent_id: UUID,
    messages: List[Dict[str, str]],
    llm_provider: ModelProvider,
    llm_model: str,
    llm_config: Optional[Dict[str, Any]] = None,
    credential_id: Optional[UUID] = None,
    task_defaults: Optional[Dict[str, Any]] = None,
    simulated_caller: bool = False,
) -> tuple[str, List[Dict[str, Any]]]:
    """Run LiteLLM with search_knowledge_base tool until assistant text or round cap.

    ``simulated_caller`` searches the test agent's knowledge bases instead of the
    production agent's.
    """
    provider = KnowledgeBaseToolProvider(
        db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        llm_model=llm_model,
        role=KB_ROLE_TEST if simulated_caller else KB_ROLE_PRODUCTION,
    )
    text, _records = run_tool_loop(
        db,
        toolset=Toolset([provider]),
        messages=with_knowledge_base_instructions(messages, simulated_caller=simulated_caller),
        organization_id=organization_id,
        llm_provider=llm_provider,
        llm_model=llm_model,
        llm_config=llm_config,
        credential_id=credential_id,
        task_defaults=task_defaults,
        max_rounds=MAX_TOOL_ROUNDS,
        side="test" if simulated_caller else "production",
    )
    return text, provider.legacy_log
