"""LLM service for prompt improvement suggestions from evaluation clusters."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.models.database import CallImportEvaluation, PromptPartial
from app.models.schemas import (
    EvaluationMetricClustersState,
    EvaluationPromptImprovementsState,
    MetricCluster,
    MetricClusterGroup,
    PromptImprovementSuggestion,
)
from app.services.agent_flowchart import _extract_json_object
from app.services.ai.llm_resolver import get_llm_provider_and_model
from app.services.ai.llm_service import llm_service
from app.services.imported_agent_constants import IMPORTED_AGENT_TAG

_IMPROVEMENTS_SYSTEM_PROMPT = (
    "You are a senior voice-agent prompt engineer. Given a production agent "
    "prompt and failure diagnostics from a call evaluation, suggest concrete "
    "prompt edits that would reduce the highest-impact failure clusters.\n\n"
    "Return STRICT JSON only:\n"
    "{\n"
    '  "overview": "<2-3 sentence executive summary>",\n'
    '  "suggestions": [\n'
    "    {\n"
    '      "metric_id": "<id>",\n'
    '      "metric_name": "<name>",\n'
    '      "cluster_id": "<id>",\n'
    '      "cluster_label": "<label>",\n'
    '      "gap_label": "LOGIC_GAP|UNDERSPEC|EXISTS_NO_TRIGGER|MISSING",\n'
    '      "share_pct": 12.5,\n'
    '      "priority": "high|medium|low",\n'
    '      "target_section": "<prompt section to edit or add>",\n'
    '      "current_gap": "<what is wrong today>",\n'
    '      "suggested_text": "<exact markdown text to add or replace>",\n'
    '      "rationale": "<why this reduces the cluster>"\n'
    "    }\n"
    "  ]\n"
    "}\n\n"
    "Gap label guidance:\n"
    "- MISSING: add absent policy, fallback, or handoff rule.\n"
    "- UNDERSPEC: clarify vague or ambiguous instructions.\n"
    "- EXISTS_NO_TRIGGER: add explicit trigger conditions.\n"
    "- LOGIC_GAP: fix routing, loops, or state-machine errors.\n\n"
    "Constraints:\n"
    "- Prioritize clusters with high share_pct and high metric failure deltas.\n"
    "- suggested_text must be copy-paste ready markdown.\n"
    "- Do not invent capabilities not implied by the prompt or clusters.\n"
    "- 3-12 suggestions; no markdown wrapper, no preamble."
)


def is_imported_agent(partial: PromptPartial) -> bool:
    tags = partial.tags if isinstance(partial.tags, list) else []
    return IMPORTED_AGENT_TAG in tags


def prompt_improvements_state_from_raw(
    raw: Any,
    *,
    completed_rows: int,
) -> EvaluationPromptImprovementsState:
    if not isinstance(raw, dict):
        return EvaluationPromptImprovementsState(status="idle")

    suggestions: List[PromptImprovementSuggestion] = []
    for item in raw.get("suggestions") or []:
        if not isinstance(item, dict):
            continue
        try:
            suggestions.append(PromptImprovementSuggestion(**item))
        except Exception:
            continue

    generated_at_completed = int(raw.get("generated_at_completed_rows") or 0)
    is_stale = (
        raw.get("status") == "completed"
        and generated_at_completed > 0
        and completed_rows > generated_at_completed
    )

    return EvaluationPromptImprovementsState(
        status=raw.get("status") or "idle",
        imported_agent_id=raw.get("imported_agent_id"),
        imported_agent_name=raw.get("imported_agent_name"),
        suggestions=suggestions,
        overview=raw.get("overview"),
        generated_at=raw.get("generated_at"),
        generated_at_completed_rows=generated_at_completed,
        provider=raw.get("provider"),
        model=raw.get("model"),
        error_message=raw.get("error_message"),
        is_stale=is_stale,
    )


def prompt_improvements_state_to_db(
    state: EvaluationPromptImprovementsState,
) -> Dict[str, Any]:
    payload = state.model_dump(mode="json")
    if state.generated_at and hasattr(state.generated_at, "isoformat"):
        payload["generated_at"] = state.generated_at.isoformat()
    return payload


def _top_clusters_for_metric(group: MetricClusterGroup, limit: int = 5) -> List[MetricCluster]:
    return sorted(
        group.clusters,
        key=lambda c: (-c.share_pct, -c.count, c.label),
    )[:limit]


def _build_cluster_context(
    clusters_state: EvaluationMetricClustersState,
    period_deltas: Optional[Dict[str, Dict[str, str]]] = None,
) -> List[Dict[str, Any]]:
    context: List[Dict[str, Any]] = []
    for group in clusters_state.groups:
        delta = (period_deltas or {}).get(group.metric_id, {})
        for cluster in _top_clusters_for_metric(group):
            context.append(
                {
                    "metric_id": group.metric_id,
                    "metric_name": group.metric_name,
                    "cluster_id": cluster.id,
                    "cluster_label": cluster.label,
                    "gap_label": cluster.gap_label,
                    "share_pct": cluster.share_pct,
                    "count": cluster.count,
                    "observation": cluster.observation,
                    "failure_reason": cluster.failure_reason or group.failure_reason,
                    "metric_failure_delta_label": delta.get("label"),
                    "metric_failure_delta_detail": delta.get("detail"),
                }
            )
    context.sort(
        key=lambda item: (
            -float(item.get("share_pct") or 0),
            -float(item.get("count") or 0),
        )
    )
    return context[:25]


def _parse_delta_pp(delta_label: Optional[str]) -> float:
    if not delta_label:
        return 0.0
    match = re.search(r"([+-]?\d+(?:\.\d+)?)\s*pp", str(delta_label))
    if not match:
        return 0.0
    try:
        return abs(float(match.group(1)))
    except ValueError:
        return 0.0


def _priority_from_share(share_pct: float, delta_label: Optional[str]) -> str:
    share = float(share_pct or 0)
    delta = _parse_delta_pp(delta_label)
    if share >= 20 or delta >= 5:
        return "high"
    if share >= 10 or delta >= 2:
        return "medium"
    return "low"


def _parse_suggestions(
    raw: Dict[str, Any],
    cluster_context: List[Dict[str, Any]],
) -> Tuple[str, List[PromptImprovementSuggestion]]:
    overview = str(raw.get("overview") or "").strip()
    suggestions_raw = raw.get("suggestions")
    if not isinstance(suggestions_raw, list):
        raise ValueError("Improvements JSON must include suggestions[]")

    cluster_lookup = {
        (str(item["metric_id"]), str(item["cluster_id"])): item
        for item in cluster_context
    }

    suggestions: List[PromptImprovementSuggestion] = []
    for item in suggestions_raw:
        if not isinstance(item, dict):
            continue
        metric_id = str(item.get("metric_id") or "").strip()
        cluster_id = str(item.get("cluster_id") or "").strip()
        if not metric_id or not cluster_id:
            continue
        lookup = cluster_lookup.get((metric_id, cluster_id), {})
        share_pct = float(item.get("share_pct") or lookup.get("share_pct") or 0)
        priority = str(item.get("priority") or "").strip().lower()
        if priority not in {"high", "medium", "low"}:
            priority = _priority_from_share(
                share_pct,
                lookup.get("metric_failure_delta_label"),
            )
        raw_gap = str(
            item.get("gap_label") or lookup.get("gap_label") or "UNDERSPEC"
        ).strip().upper()
        if raw_gap not in {
            "LOGIC_GAP",
            "UNDERSPEC",
            "EXISTS_NO_TRIGGER",
            "MISSING",
        }:
            raw_gap = "UNDERSPEC"
        suggestions.append(
            PromptImprovementSuggestion(
                id=str(item.get("id") or uuid.uuid4()),
                metric_id=metric_id,
                metric_name=str(item.get("metric_name") or lookup.get("metric_name") or ""),
                cluster_id=cluster_id,
                cluster_label=str(
                    item.get("cluster_label") or lookup.get("cluster_label") or ""
                ),
                gap_label=raw_gap,
                share_pct=share_pct,
                priority=priority,
                target_section=str(item.get("target_section") or "").strip(),
                current_gap=str(item.get("current_gap") or "").strip(),
                suggested_text=str(item.get("suggested_text") or "").strip(),
                rationale=str(item.get("rationale") or "").strip(),
            )
        )
    return overview, suggestions


def generate_prompt_improvements(
    *,
    evaluation: CallImportEvaluation,
    imported_agent: PromptPartial,
    clusters_state: EvaluationMetricClustersState,
    organization_id: UUID,
    db: Session,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    period_deltas: Optional[Dict[str, Dict[str, str]]] = None,
) -> EvaluationPromptImprovementsState:
    if clusters_state.status != "completed" or not clusters_state.groups:
        raise ValueError("Metric clusters must be completed before generating improvements")

    cluster_context = _build_cluster_context(clusters_state, period_deltas)
    if not cluster_context:
        raise ValueError("No cluster context available for prompt improvements")

    provider_enum, model_str = get_llm_provider_and_model(
        organization_id,
        db,
        provider,
        model,
    )

    rca_prompt_areas = []
    if clusters_state.rca_summary and clusters_state.rca_summary.prompt_areas:
        rca_prompt_areas = [
            area.model_dump(mode="json")
            for area in clusters_state.rca_summary.prompt_areas
        ]

    user_payload = {
        "agent_name": imported_agent.name,
        "agent_prompt": imported_agent.content,
        "failure_clusters": cluster_context,
        "rca_prompt_areas": rca_prompt_areas,
        "rca_overview": (
            clusters_state.rca_summary.model_dump(mode="json")
            if clusters_state.rca_summary
            else None
        ),
    }

    messages = [
        {"role": "system", "content": _IMPROVEMENTS_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(user_payload, ensure_ascii=False),
        },
    ]

    result = llm_service.generate_response(
        messages=messages,
        llm_provider=provider_enum,
        llm_model=model_str,
        organization_id=organization_id,
        db=db,
        temperature=0.3,
        max_tokens=6000,
    )
    raw = _extract_json_object(result["text"])
    overview, suggestions = _parse_suggestions(raw, cluster_context)

    return EvaluationPromptImprovementsState(
        status="completed",
        imported_agent_id=str(imported_agent.id),
        imported_agent_name=imported_agent.name,
        suggestions=suggestions,
        overview=overview or None,
        generated_at=datetime.now(timezone.utc),
        generated_at_completed_rows=evaluation.completed_rows,
        provider=provider_enum.value,
        model=model_str,
        error_message=None,
        is_stale=False,
    )
