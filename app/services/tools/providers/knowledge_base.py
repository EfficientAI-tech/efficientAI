"""``search_knowledge_base`` as a tool provider over the agent's attached knowledge bases."""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.services.knowledge_bases.agent_links import KB_ROLE_PRODUCTION
from app.services.knowledge_bases.retrieval import (
    format_search_results_for_tool,
    search_knowledge_base,
)
from app.services.knowledge_bases.tool_call_logging import record_knowledge_base_tool_call
from app.services.knowledge_bases.tool_schema import search_knowledge_base_tool_definition
from app.services.tools.base import ToolResult, ToolSpec

KNOWLEDGE_BASE_PROVIDER = "knowledge_base"
KNOWLEDGE_BASE_TOOL = "search_knowledge_base"


class KnowledgeBaseToolProvider:
    name = KNOWLEDGE_BASE_PROVIDER

    def __init__(
        self,
        db: Session,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        agent_id: UUID,
        channel: str = "chat_tools",
        llm_model: Optional[str] = None,
        role: str = KB_ROLE_PRODUCTION,
    ):
        self.db = db
        self.organization_id = organization_id
        self.workspace_id = workspace_id
        self.agent_id = agent_id
        self.channel = channel
        self.llm_model = llm_model
        self.role = role
        # Legacy-shaped log ({tool, query, hit_count, ...}) kept for existing callers.
        self.legacy_log: list[dict[str, Any]] = []

    def list_tools(self) -> list[ToolSpec]:
        fn = search_knowledge_base_tool_definition()["function"]
        return [
            ToolSpec(
                name=fn["name"],
                description=fn["description"],
                parameters=fn["parameters"],
                provider=self.name,
            )
        ]

    def call(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        query = str(arguments.get("query") or "").strip()
        if not query:
            return ToolResult("search_knowledge_base needs a non-empty query.", is_error=True)
        hits = search_knowledge_base(
            self.db,
            organization_id=self.organization_id,
            workspace_id=self.workspace_id,
            agent_id=self.agent_id,
            query=query,
            role=self.role,
        )
        record_knowledge_base_tool_call(
            channel=self.channel,
            query=query,
            hit_count=len(hits),
            agent_id=str(self.agent_id),
            llm_model=self.llm_model,
            tool_calls_log=self.legacy_log,
        )
        documents = sorted({hit.get("document_name") or "document" for hit in hits})
        return ToolResult(
            format_search_results_for_tool(hits),
            extra={"hit_count": len(hits), "documents": documents},
        )
