"""Tool-aware chat completion for internal production simulation."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.enums import ModelProvider
from app.services.ai.llm_service import llm_service
from app.services.knowledge_bases.prompt import append_knowledge_base_instructions
from app.services.knowledge_bases.retrieval import format_search_results_for_tool, search_knowledge_base
from app.services.knowledge_bases.tool_call_logging import record_knowledge_base_tool_call
from app.services.knowledge_bases.tool_schema import knowledge_base_tools

MAX_TOOL_ROUNDS = 3


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
) -> tuple[str, List[Dict[str, Any]]]:
    """Run LiteLLM with search_knowledge_base tool until assistant text or round cap."""
    tool_calls_log: List[Dict[str, Any]] = []
    working_messages = list(messages)
    if working_messages and working_messages[0].get("role") == "system":
        working_messages[0] = {
            "role": "system",
            "content": append_knowledge_base_instructions(working_messages[0].get("content") or ""),
        }

    def execute_tool(name: str, arguments: Dict[str, Any]) -> str:
        if name != "search_knowledge_base":
            return f"Unknown tool: {name}"
        query = str(arguments.get("query") or "").strip()
        hits = search_knowledge_base(
            db,
            organization_id=organization_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            query=query,
        )
        formatted = format_search_results_for_tool(hits)
        record_knowledge_base_tool_call(
            channel="chat_tools",
            query=query,
            hit_count=len(hits),
            agent_id=str(agent_id),
            llm_model=llm_model,
            tool_calls_log=tool_calls_log,
        )
        if tool_calls_log:
            tool_calls_log[-1]["tool"] = name
        return formatted

    for _ in range(MAX_TOOL_ROUNDS):
        result = llm_service.generate_response_with_tools(
            messages=working_messages,
            tools=knowledge_base_tools(),
            llm_provider=llm_provider,
            llm_model=llm_model,
            organization_id=organization_id,
            db=db,
            llm_config=llm_config,
            credential_id=credential_id,
            task_defaults=task_defaults,
        )
        if result.get("tool_calls"):
            assistant_msg = {
                "role": "assistant",
                "content": result.get("text") or None,
                "tool_calls": result["tool_calls"],
            }
            working_messages.append(assistant_msg)
            for call in result["tool_calls"]:
                fn = call.get("function") or {}
                name = fn.get("name") or ""
                raw_args = fn.get("arguments") or "{}"
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                except json.JSONDecodeError:
                    args = {}
                tool_result = execute_tool(name, args)
                working_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id"),
                        "content": tool_result,
                    }
                )
            continue
        text = (result.get("text") or "").strip()
        return text, tool_calls_log
    final = llm_service.generate_response(
        messages=working_messages,
        llm_provider=llm_provider,
        llm_model=llm_model,
        organization_id=organization_id,
        db=db,
        llm_config=llm_config,
        credential_id=credential_id,
        task_defaults=task_defaults,
    )
    return (final.get("text") or "").strip(), tool_calls_log
