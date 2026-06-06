"""LLM service for generating agent logic flowcharts from production prompts."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.models.enums import ModelProvider
from app.models.schemas import AgentFlowEdge, AgentFlowGraph, AgentFlowNode
from app.services.ai.llm_resolver import get_llm_provider_and_model
from app.services.ai.llm_service import llm_service

_FLOWCHART_SYSTEM_PROMPT = (
    "You are a senior voice-agent architect. Given a production agent system "
    "prompt, infer the agent's conversational logic as a directed flowchart.\n\n"
    "Return STRICT JSON only:\n"
    "{\n"
    '  "nodes": [\n'
    '    {"id": "start", "label": "Call Start", "node_type": "start"},\n'
    '    {"id": "n1", "label": "Greet caller", "node_type": "action"},\n'
    '    {"id": "d1", "label": "Intent identified?", "node_type": "decision"},\n'
    '    {"id": "end", "label": "End call", "node_type": "terminal"}\n'
    "  ],\n"
    '  "edges": [\n'
    '    {"source": "start", "target": "n1", "condition": null},\n'
    '    {"source": "d1", "target": "n2", "condition": "yes"},\n'
    '    {"source": "d1", "target": "n3", "condition": "no"}\n'
    "  ]\n"
    "}\n\n"
    "Rules:\n"
    "- node_type must be one of: start, decision, action, terminal.\n"
    "- Exactly one start node; at least one terminal node.\n"
    "- decision nodes should have 2+ outgoing edges with condition labels "
    "(yes/no, true/false, or descriptive).\n"
    "- Capture if/else branches, loops, handoffs, and escalation paths.\n"
    "- Use short, readable labels (<=40 chars).\n"
    "- Prefer 6-14 nodes; merge minor steps to stay compact.\n"
    "- Keep the graph acyclic except for explicit loop-back edges.\n"
    "- Output compact JSON with no whitespace padding.\n"
    "- No markdown, no preamble."
)


def _extract_json_object(text: str) -> Dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("LLM response did not contain a JSON object")
    return json.loads(cleaned[start : end + 1])


def _normalize_node_type(raw: Any) -> str:
    value = str(raw or "action").strip().lower()
    if value in {"start", "decision", "action", "terminal"}:
        return value
    return "action"


def _parse_flowchart_payload(
    raw: Dict[str, Any],
    *,
    provider: str,
    model: str,
) -> AgentFlowGraph:
    nodes_raw = raw.get("nodes")
    edges_raw = raw.get("edges")
    if not isinstance(nodes_raw, list) or not isinstance(edges_raw, list):
        raise ValueError("Flowchart JSON must include nodes[] and edges[]")

    nodes: List[AgentFlowNode] = []
    seen_ids: set[str] = set()
    for item in nodes_raw:
        if not isinstance(item, dict):
            continue
        node_id = str(item.get("id") or "").strip()
        label = str(item.get("label") or "").strip()
        if not node_id or not label:
            continue
        if node_id in seen_ids:
            continue
        seen_ids.add(node_id)
        pos_x = item.get("position_x")
        pos_y = item.get("position_y")
        nodes.append(
            AgentFlowNode(
                id=node_id,
                label=label[:120],
                node_type=_normalize_node_type(item.get("node_type")),
                position_x=float(pos_x) if pos_x is not None else None,
                position_y=float(pos_y) if pos_y is not None else None,
            )
        )

    if not nodes:
        raise ValueError("Flowchart must include at least one node")

    node_ids = {n.id for n in nodes}
    edges: List[AgentFlowEdge] = []
    for item in edges_raw:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "").strip()
        target = str(item.get("target") or "").strip()
        if not source or not target:
            continue
        if source not in node_ids or target not in node_ids:
            continue
        condition = item.get("condition")
        edges.append(
            AgentFlowEdge(
                source=source,
                target=target,
                condition=str(condition).strip()[:80] if condition else None,
            )
        )

    return AgentFlowGraph(
        nodes=nodes,
        edges=edges,
        generated_at=datetime.now(timezone.utc),
        provider=provider,
        model=model,
    )


def generate_agent_flowchart(
    *,
    prompt_text: str,
    organization_id: UUID,
    db: Session,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> Tuple[AgentFlowGraph, ModelProvider, str]:
    """Generate a flowchart graph from a production agent prompt."""
    if not prompt_text.strip():
        raise ValueError("Prompt text is required")

    provider_enum, model_str = get_llm_provider_and_model(
        organization_id,
        db,
        provider,
        model,
    )

    messages = [
        {"role": "system", "content": _FLOWCHART_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Analyze this production agent prompt and return the logic "
                "flowchart JSON:\n\n"
                f"{prompt_text[:120000]}"
            ),
        },
    ]

    max_tokens_attempts = (8000, 16000)
    result: Dict[str, Any] = {}
    for attempt_idx, max_tokens in enumerate(max_tokens_attempts):
        result = llm_service.generate_response(
            messages=messages,
            llm_provider=provider_enum,
            llm_model=model_str,
            organization_id=organization_id,
            db=db,
            temperature=0.2,
            max_tokens=max_tokens,
        )
        if not result.get("truncated"):
            break
        if attempt_idx < len(max_tokens_attempts) - 1:
            logger.warning(
                "Agent flowchart output truncated at max_tokens={}; retrying with {}",
                max_tokens,
                max_tokens_attempts[attempt_idx + 1],
            )
        else:
            raise ValueError(
                "LLM output was truncated before completing the flowchart JSON. "
                "Try a model with a larger output window or pick a different provider."
            )

    try:
        raw = _extract_json_object(result["text"])
    except (ValueError, json.JSONDecodeError) as exc:
        if result.get("truncated"):
            raise ValueError(
                "LLM output was truncated before completing the flowchart JSON. "
                "Try a model with a larger output window or pick a different provider."
            ) from exc
        raise
    graph = _parse_flowchart_payload(
        raw,
        provider=provider_enum.value,
        model=model_str,
    )
    logger.info(
        "Generated agent flowchart: {} nodes, {} edges",
        len(graph.nodes),
        len(graph.edges),
    )
    return graph, provider_enum, model_str
