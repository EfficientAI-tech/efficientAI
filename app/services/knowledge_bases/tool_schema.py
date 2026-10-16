"""OpenAI-style tool definition for knowledge search."""

from __future__ import annotations

from typing import Any, Dict, List


def search_knowledge_base_tool_definition() -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": (
                "Search attached knowledge bases for relevant passages from uploaded documents."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language search query.",
                    }
                },
                "required": ["query"],
            },
        },
    }


def knowledge_base_tools() -> List[Dict[str, Any]]:
    return [search_knowledge_base_tool_definition()]
