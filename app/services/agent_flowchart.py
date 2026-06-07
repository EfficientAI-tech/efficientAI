"""LLM service for generating agent logic flowcharts from production prompts."""

from __future__ import annotations

import hashlib
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
    '    {"id": "start", "label": "Call Start", "node_type": "start", '
    '"start_offset": 0, "end_offset": 120},\n'
    '    {"id": "n1", "label": "Greet caller", "node_type": "action", '
    '"start_offset": 121, "end_offset": 340},\n'
    '    {"id": "d1", "label": "Intent identified?", "node_type": "decision", '
    '"start_offset": 341, "end_offset": 520},\n'
    '    {"id": "end", "label": "End call", "node_type": "terminal", '
    '"start_offset": 521, "end_offset": 600}\n'
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
    "- For each node, include start_offset/end_offset (0-based character indices "
    "into the prompt). Do NOT include prompt text in the response.\n"
    "- Map every node to the prompt section that instructs that logic step.\n"
    "- Output compact JSON with no whitespace padding.\n"
    "- No markdown, no preamble."
)

_BATCH_NODE_MAP_SYSTEM_PROMPT = (
    "You are a senior voice-agent architect. Given a production agent prompt "
    "and an existing flowchart (nodes only), locate the character span in the "
    "prompt that instructs each node's behavior.\n\n"
    "Return STRICT JSON only:\n"
    "{\n"
    '  "node_mappings": [\n'
    '    {"id": "n1", "start_offset": 0, "end_offset": 120}\n'
    "  ]\n"
    "}\n\n"
    "Rules:\n"
    "- Return one entry per input node id.\n"
    "- start_offset and end_offset are 0-based character indices into agent_prompt.\n"
    "- end_offset must be greater than start_offset.\n"
    "- Do NOT include prompt text in the response — offsets only.\n"
    "- agent_prompt[start_offset:end_offset] must be the most specific section "
    "for that node.\n"
    "- Prefer the most specific contiguous section for each node.\n"
    "- Output compact JSON with no whitespace padding.\n"
    "- No markdown, no preamble."
)


def compute_prompt_content_hash(prompt_text: str) -> str:
    return hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()


def node_has_valid_mapping(node: AgentFlowNode, prompt_text: str) -> bool:
    if node.start_offset is not None and node.end_offset is not None:
        start = node.start_offset
        end = node.end_offset
        if end <= start or end > len(prompt_text):
            return False
        span = prompt_text[start:end]
        if node.prompt_excerpt:
            return span == node.prompt_excerpt
        return True
    if node.prompt_excerpt:
        return node.prompt_excerpt in prompt_text
    return False


def strip_node_prompt_mappings(graph: AgentFlowGraph) -> AgentFlowGraph:
    cleared_nodes = [
        node.model_copy(
            update={
                "prompt_excerpt": None,
                "start_offset": None,
                "end_offset": None,
            }
        )
        for node in graph.nodes
    ]
    return graph.model_copy(
        update={
            "nodes": cleared_nodes,
            "prompt_content_hash": None,
        }
    )


def apply_prompt_hash_staleness(
    graph: AgentFlowGraph,
    prompt_text: str,
) -> AgentFlowGraph:
    current_hash = compute_prompt_content_hash(prompt_text)
    if graph.prompt_content_hash == current_hash:
        return graph
    return strip_node_prompt_mappings(graph)


def count_mapped_nodes(graph: AgentFlowGraph, prompt_text: str) -> int:
    return sum(1 for node in graph.nodes if node_has_valid_mapping(node, prompt_text))


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


def _find_excerpt_in_prompt(prompt_text: str, excerpt: str) -> Optional[Tuple[int, int]]:
    excerpt = excerpt.strip()
    if not excerpt:
        return None
    idx = prompt_text.find(excerpt)
    if idx >= 0:
        return idx, idx + len(excerpt)
    return None


def _resolve_prompt_span(
    prompt_text: str,
    *,
    excerpt: Optional[str],
    start_offset: Any,
    end_offset: Any,
) -> Tuple[Optional[str], Optional[int], Optional[int]]:
    excerpt_str = str(excerpt or "").strip()
    if excerpt_str:
        found = _find_excerpt_in_prompt(prompt_text, excerpt_str)
        if found:
            start, end = found
            return prompt_text[start:end], start, end

    try:
        start = int(float(start_offset))
        end = int(float(end_offset))
    except (TypeError, ValueError):
        return excerpt_str or None, None, None

    if 0 <= start < end <= len(prompt_text):
        return prompt_text[start:end], start, end

    return excerpt_str or None, None, None


_NODE_MAP_CHUNK_SIZE = 8


def _heuristic_map_node(
    node: AgentFlowNode,
    prompt_text: str,
) -> Tuple[Optional[str], Optional[int], Optional[int]]:
    """Best-effort section lookup using the node label when LLM mapping is missing."""
    label = node.label.strip()
    if not label or len(label) < 4:
        return None, None, None

    search_terms = [label]
    for sep in ("?", ",", "&"):
        if sep in label:
            fragment = label.split(sep)[0].strip()
            if len(fragment) >= 4:
                search_terms.append(fragment)

    prompt_lower = prompt_text.lower()
    for term in search_terms:
        idx = prompt_lower.find(term.lower())
        if idx < 0:
            continue
        start = prompt_text.rfind("\n\n", 0, idx)
        start = 0 if start < 0 else start + 2
        end = prompt_text.find("\n\n", idx + len(term))
        if end < 0:
            end = len(prompt_text)
        if end <= start:
            continue
        excerpt = prompt_text[start:end]
        if len(excerpt.strip()) >= 40:
            return excerpt, start, end

    return None, None, None


def _llm_map_node_chunk(
    *,
    prompt_text: str,
    nodes: List[AgentFlowNode],
    organization_id: UUID,
    db: Session,
    provider_enum: ModelProvider,
    model_str: str,
) -> Dict[str, Dict[str, Any]]:
    """Map a chunk of nodes to prompt offsets via one LLM call."""
    user_payload = {
        "agent_prompt": prompt_text[:120000],
        "nodes": [
            {
                "id": node.id,
                "label": node.label,
                "node_type": node.node_type,
            }
            for node in nodes
        ],
    }
    messages = [
        {"role": "system", "content": _BATCH_NODE_MAP_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(user_payload, ensure_ascii=False),
        },
    ]

    max_tokens_attempts = (2000, 4000, 8000)
    last_parse_error: Optional[Exception] = None
    raw: Dict[str, Any] = {}
    result: Dict[str, Any] = {}
    for attempt_idx, max_tokens in enumerate(max_tokens_attempts):
        result = llm_service.generate_response(
            messages=messages,
            llm_provider=provider_enum,
            llm_model=model_str,
            organization_id=organization_id,
            db=db,
            temperature=0.1,
            max_tokens=max_tokens,
        )
        try:
            raw = _extract_json_object(result["text"])
            last_parse_error = None
            break
        except (ValueError, json.JSONDecodeError) as exc:
            last_parse_error = exc
            if attempt_idx < len(max_tokens_attempts) - 1:
                continue
            raise ValueError(
                f"LLM returned invalid JSON for node mapping chunk ({len(nodes)} nodes)."
            ) from exc

    if last_parse_error is not None:
        raise ValueError(
            f"LLM returned invalid JSON for node mapping chunk ({len(nodes)} nodes)."
        ) from last_parse_error

    mappings_raw = raw.get("node_mappings")
    if not isinstance(mappings_raw, list):
        raise ValueError("Batch node mapping JSON must include node_mappings[]")

    mapping_by_id: Dict[str, Dict[str, Any]] = {}
    for item in mappings_raw:
        if not isinstance(item, dict):
            continue
        node_id = str(item.get("id") or "").strip()
        if node_id:
            mapping_by_id[node_id] = item
    return mapping_by_id


def _apply_mappings_to_nodes(
    *,
    prompt_text: str,
    nodes: List[AgentFlowNode],
    mapping_by_id: Dict[str, Dict[str, Any]],
    use_heuristic_fallback: bool = True,
) -> List[AgentFlowNode]:
    updated_nodes: List[AgentFlowNode] = []
    for node in nodes:
        mapping = mapping_by_id.get(node.id, {})
        excerpt, start, end = _resolve_prompt_span(
            prompt_text,
            excerpt=None,
            start_offset=mapping.get("start_offset"),
            end_offset=mapping.get("end_offset"),
        )
        if start is None and use_heuristic_fallback:
            excerpt, start, end = _heuristic_map_node(node, prompt_text)
        updated_nodes.append(
            node.model_copy(
                update={
                    "prompt_excerpt": excerpt,
                    "start_offset": start,
                    "end_offset": end,
                }
            )
        )
    return updated_nodes


def _parse_flowchart_payload(
    raw: Dict[str, Any],
    *,
    provider: str,
    model: str,
    prompt_text: str = "",
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
        excerpt, start, end = _resolve_prompt_span(
            prompt_text,
            excerpt=None,
            start_offset=item.get("start_offset"),
            end_offset=item.get("end_offset"),
        )
        nodes.append(
            AgentFlowNode(
                id=node_id,
                label=label[:120],
                node_type=_normalize_node_type(item.get("node_type")),
                position_x=float(pos_x) if pos_x is not None else None,
                position_y=float(pos_y) if pos_y is not None else None,
                prompt_excerpt=excerpt,
                start_offset=start,
                end_offset=end,
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

    content_hash = compute_prompt_content_hash(prompt_text) if prompt_text else None
    return AgentFlowGraph(
        nodes=nodes,
        edges=edges,
        generated_at=datetime.now(timezone.utc),
        provider=provider,
        model=model,
        prompt_content_hash=content_hash,
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
        prompt_text=prompt_text,
    )
    logger.info(
        "Generated agent flowchart: {} nodes, {} edges",
        len(graph.nodes),
        len(graph.edges),
    )
    return graph, provider_enum, model_str


def map_all_flow_nodes_to_prompt(
    *,
    prompt_text: str,
    graph: AgentFlowGraph,
    organization_id: UUID,
    db: Session,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> AgentFlowGraph:
    """Locate prompt excerpts for all flowchart nodes via chunked LLM calls."""
    if not prompt_text.strip():
        raise ValueError("Prompt text is required")
    if not graph.nodes:
        raise ValueError("Flowchart must include at least one node")

    provider_enum, model_str = get_llm_provider_and_model(
        organization_id,
        db,
        provider,
        model,
    )

    mapping_by_id: Dict[str, Dict[str, Any]] = {}
    chunks = [
        graph.nodes[index : index + _NODE_MAP_CHUNK_SIZE]
        for index in range(0, len(graph.nodes), _NODE_MAP_CHUNK_SIZE)
    ]
    for chunk_idx, chunk in enumerate(chunks):
        try:
            chunk_mappings = _llm_map_node_chunk(
                prompt_text=prompt_text,
                nodes=chunk,
                organization_id=organization_id,
                db=db,
                provider_enum=provider_enum,
                model_str=model_str,
            )
            mapping_by_id.update(chunk_mappings)
            logger.info(
                "Mapped node chunk {}/{}: {} LLM entries for {} nodes",
                chunk_idx + 1,
                len(chunks),
                len(chunk_mappings),
                len(chunk),
            )
        except Exception as exc:
            logger.warning(
                "Node mapping chunk {}/{} failed: {}",
                chunk_idx + 1,
                len(chunks),
                repr(exc),
            )

    updated_nodes = _apply_mappings_to_nodes(
        prompt_text=prompt_text,
        nodes=graph.nodes,
        mapping_by_id=mapping_by_id,
        use_heuristic_fallback=True,
    )

    mapped_count = sum(
        1 for node in updated_nodes if node_has_valid_mapping(node, prompt_text)
    )
    if mapped_count == 0:
        raise ValueError(
            "No prompt sections could be mapped to flowchart nodes. "
            "Try regenerating the flowchart with fewer nodes or a different model."
        )

    if mapped_count < len(updated_nodes):
        logger.warning(
            "Partial node mapping: {}/{} nodes mapped",
            mapped_count,
            len(updated_nodes),
        )

    return graph.model_copy(
        update={
            "nodes": updated_nodes,
            "prompt_content_hash": compute_prompt_content_hash(prompt_text),
        }
    )
