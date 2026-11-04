"""Batched prompt-improvement generation with checkpoints and cancel support."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.models.database import CallImportEvaluation, PromptPartial
from app.models.schemas import (
    EvaluationMetricClustersState,
    EvaluationPromptImprovementsState,
    PromptImprovementSuggestion,
)
from app.services.agent_flowchart import _extract_json_object
from app.services.call_import_prompt_improvements import (
    _IMPROVEMENTS_SYSTEM_PROMPT,
    _build_cluster_context,
    _extract_flow_nodes,
    _parse_suggestions,
    prompt_improvements_state_to_db,
)
from app.services.evaluation_analysis_checkpoints import (
    JOB_KIND_PROMPT_IMPROVEMENTS,
    PROMPT_IMPROVEMENTS_CANCELLED_BY_USER_ERROR,
    list_analysis_batches,
    prompt_improvements_raw_is_cancelled,
    upsert_analysis_batch,
)
from app.services.ai.llm_resolver import get_llm_provider_and_model_for_request
from app.services.ai.llm_service import llm_service

CancelCheck = Callable[[], bool]


def _suggestions_from_batches(
    batches: Sequence[Any],
) -> Tuple[Optional[str], List[PromptImprovementSuggestion]]:
    overview: Optional[str] = None
    suggestions: List[PromptImprovementSuggestion] = []
    for batch in batches:
        payload = batch.payload if isinstance(batch.payload, dict) else {}
        if overview is None and isinstance(payload.get("overview"), str):
            overview = payload.get("overview")
        raw_items = payload.get("suggestions")
        if isinstance(raw_items, list):
            for item in raw_items:
                if isinstance(item, dict):
                    try:
                        suggestions.append(PromptImprovementSuggestion(**item))
                    except Exception:  # noqa: BLE001
                        continue
    return overview, suggestions


def process_prompt_improvements_wave_step(
    db: Session,
    evaluation: CallImportEvaluation,
    imported_agent: PromptPartial,
    clusters_state: EvaluationMetricClustersState,
    organization_id: UUID,
    *,
    job_run_id: UUID,
    provider: Optional[str],
    model: Optional[str],
    credential_id: Optional[UUID],
    period_deltas: Optional[Dict[str, Dict[str, str]]] = None,
    is_cancelled: Optional[CancelCheck] = None,
) -> Tuple[str, Optional[EvaluationPromptImprovementsState]]:
    raw = evaluation.prompt_improvements if isinstance(evaluation.prompt_improvements, dict) else {}
    if prompt_improvements_raw_is_cancelled(raw):
        return "idle", EvaluationPromptImprovementsState(
            status="cancelled",
            imported_agent_id=str(imported_agent.id),
            imported_agent_name=imported_agent.name,
            error_message=PROMPT_IMPROVEMENTS_CANCELLED_BY_USER_ERROR,
            generated_at=datetime.now(timezone.utc),
        )

    completed_groups = {
        str(x) for x in (raw.get("completed_group_metric_ids") or []) if x
    }
    groups = list(clusters_state.groups or [])
    pending = [g for g in groups if str(g.metric_id) not in completed_groups]
    if not pending:
        batches = list_analysis_batches(
            db,
            evaluation_id=evaluation.id,
            job_kind=JOB_KIND_PROMPT_IMPROVEMENTS,
            job_run_id=job_run_id,
        )
        overview, suggestions = _suggestions_from_batches(batches)
        provider_enum, model_str = get_llm_provider_and_model_for_request(
            organization_id,
            db,
            provider,
            model,
            credential_id,
        )
        return "done", EvaluationPromptImprovementsState(
            status="completed",
            imported_agent_id=str(imported_agent.id),
            imported_agent_name=imported_agent.name,
            suggestions=suggestions,
            overview=overview,
            generated_at=datetime.now(timezone.utc),
            generated_at_completed_rows=evaluation.completed_rows,
            provider=provider_enum.value,
            model=model_str,
            error_message=None,
            is_stale=False,
        )

    if is_cancelled and is_cancelled():
        return "idle", EvaluationPromptImprovementsState(
            status="cancelled",
            imported_agent_id=str(imported_agent.id),
            imported_agent_name=imported_agent.name,
            error_message=PROMPT_IMPROVEMENTS_CANCELLED_BY_USER_ERROR,
            generated_at=datetime.now(timezone.utc),
        )

    group = pending[0]
    partial_state = EvaluationMetricClustersState(
        status="completed",
        groups=[group],
    )
    cluster_context = _build_cluster_context(partial_state, period_deltas)
    if not cluster_context:
        completed_groups.add(str(group.metric_id))
        raw["completed_group_metric_ids"] = sorted(completed_groups)
        evaluation.prompt_improvements = raw
        return "continue", None

    provider_enum, model_str = get_llm_provider_and_model_for_request(
        organization_id,
        db,
        provider,
        model,
        credential_id,
    )
    flow_nodes = _extract_flow_nodes(imported_agent.agent_flowchart)
    flow_node_context = [{"id": node_id, "label": label} for node_id, label in flow_nodes.items()]
    rca_prompt_areas = []
    if clusters_state.rca_summary and clusters_state.rca_summary.prompt_areas:
        rca_prompt_areas = [
            area.model_dump(mode="json")
            for area in clusters_state.rca_summary.prompt_areas
        ]

    user_payload: Dict[str, Any] = {
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
    if flow_node_context:
        user_payload["agent_flow_nodes"] = flow_node_context

    messages = [
        {"role": "system", "content": _IMPROVEMENTS_SYSTEM_PROMPT},
        {"role": "user", "content": __import__("json").dumps(user_payload, ensure_ascii=False)},
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
    parsed = _extract_json_object(result["text"])
    overview, suggestions = _parse_suggestions(
        parsed,
        cluster_context,
        agent_prompt=imported_agent.content or "",
        flow_nodes=flow_nodes,
    )

    batch_index = len(completed_groups)
    upsert_analysis_batch(
        db,
        evaluation_id=evaluation.id,
        job_kind=JOB_KIND_PROMPT_IMPROVEMENTS,
        job_run_id=job_run_id,
        batch_index=batch_index,
        payload={
            "metric_id": str(group.metric_id),
            "overview": overview,
            "suggestions": [s.model_dump(mode="json") for s in suggestions],
        },
    )

    completed_groups.add(str(group.metric_id))
    raw["completed_group_metric_ids"] = sorted(completed_groups)
    raw["status"] = "running"
    evaluation.prompt_improvements = raw
    db.commit()
    return "continue", None
