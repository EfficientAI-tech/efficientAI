"""Register knowledge-base search on voice-bundle LLM pipelines."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from efficientai.adapters.schemas.function_schema import FunctionSchema
from efficientai.adapters.schemas.tools_schema import ToolsSchema

from app.database import SessionLocal
from app.services.knowledge_bases.agent_links import KB_ROLE_PRODUCTION
from app.services.knowledge_bases.retrieval import format_search_results_for_tool, search_knowledge_base
from app.services.knowledge_bases.tool_call_logging import KnowledgeBaseVoiceNotifier
from app.services.knowledge_bases.tool_schema import search_knowledge_base_tool_definition


def register_voice_bundle_knowledge_tools(
    llm: Any,
    context: Any,
    *,
    organization_id: str,
    workspace_id: str,
    agent_id: str,
    kb_notifier: KnowledgeBaseVoiceNotifier | None = None,
    role: str = KB_ROLE_PRODUCTION,
) -> None:
    """Attach search_knowledge_base to the bundle LLM context."""
    org_uuid = UUID(organization_id)
    ws_uuid = UUID(workspace_id)
    agent_uuid = UUID(agent_id)

    tool_def = search_knowledge_base_tool_definition()["function"]

    schema = FunctionSchema(
        name=tool_def["name"],
        description=tool_def["description"],
        properties=tool_def["parameters"]["properties"],
        required=tool_def["parameters"].get("required") or [],
    )

    async def _handler(params: Any) -> None:
        query = str((params.arguments or {}).get("query") or "").strip()
        db = SessionLocal()
        try:
            hits = search_knowledge_base(
                db,
                organization_id=org_uuid,
                workspace_id=ws_uuid,
                agent_id=agent_uuid,
                query=query,
                role=role,
            )
            text = format_search_results_for_tool(hits)
        finally:
            db.close()
        if kb_notifier is not None:
            await kb_notifier.on_tool_call(query=query, hit_count=len(hits))
        await params.result_callback(text)

    from loguru import logger

    llm.register_function(schema.name, _handler)
    context.set_tools(ToolsSchema(standard_tools=[schema]))
    logger.info(
        "[KnowledgeBase] registered voice tool {} for agent_id={}",
        schema.name,
        agent_id,
    )
