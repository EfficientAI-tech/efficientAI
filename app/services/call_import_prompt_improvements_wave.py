"""Batched prompt-improvement generation with checkpoints and cancel support."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

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
    keep_owned_header_write,
    list_analysis_batches,
    progress_header,
    prompt_improvements_raw_is_cancelled,
    stamp_job_heartbeat,
    upsert_analysis_batch,
)
from app.services.ai.llm_resolver import get_llm_provider_and_model_for_request
from app.services.ai.llm_service import llm_service

CancelCheck = Callable[[], bool]
ProgressCallback = Callable[[Dict[str, Any]], None]

PROMPT_SUGGESTION_MAX_TOKENS = 6000


def _suggestions_from_batches(
    batches: Sequence[Any],
) -> Tuple[Optional[str], List[PromptImprovementSuggestion]]:
    overview: Optional[str] = None
    suggestions: List[PromptImprovementSuggestion] = []
    seen: set[str] = set()
    for batch in batches:
        if (getattr(batch, "status", None) or "completed") != "completed":
            continue
        payload = batch.payload if isinstance(batch.payload, dict) else {}
        if overview is None and isinstance(payload.get("overview"), str):
            overview = payload.get("overview")
        raw_items = payload.get("suggestions")
        if not isinstance(raw_items, list):
            continue
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            try:
                suggestion = PromptImprovementSuggestion(**item)
            except Exception:  # noqa: BLE001
                continue
            key = suggestion.id or f"{suggestion.metric_id}:{suggestion.target_section}:{suggestion.cluster_id}"
            if key in seen:
                continue
            seen.add(key)
            suggestions.append(suggestion)
    return overview, suggestions


def _progress_for_groups(
    groups: Sequence[Any],
    completed_group_ids: set[str],
    *,
    total_metrics: int,
) -> Dict[str, Any]:
    total = max(int(total_metrics), len(groups), 1)
    done = len([g for g in groups if str(g.metric_id) in completed_group_ids])
    current = next((g for g in groups if str(g.metric_id) not in completed_group_ids), None)
    progress = progress_header(
        completed_rows=done,
        total_rows=total,
        completed_batches=done,
        total_batches=total,
        completed_llm_calls=done,
        total_llm_calls=total,
        phase="rows" if done < total else "synthesis",
    )
    progress["completed_groups"] = done
    progress["total_groups"] = total
    if current is not None:
        progress["current_metric_name"] = current.metric_name
        progress["current_metric_index"] = done + 1
        progress["total_metrics"] = total
    return progress


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
    on_progress: Optional[ProgressCallback] = None,
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
    batch_index_base = int(raw.get("completed_group_count") or 0)
    pending = [g for g in groups if str(g.metric_id) not in completed_groups]
    total_metrics = max(int(raw.get("total_groups") or 0), len(groups), 1)

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
        raw["completed_group_count"] = batch_index_base + 1
        raw["progress"] = _progress_for_groups(
            groups, completed_groups, total_metrics=total_metrics
        )
        evaluation.prompt_improvements = stamp_job_heartbeat(raw)
        flag_modified(evaluation, "prompt_improvements")
        if not keep_owned_header_write(
            db, evaluation, "prompt_improvements", job_run_id
        ):
            return "idle", None
        db.commit()
        if on_progress:
            on_progress(raw["progress"])
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
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]

    result = llm_service.generate_response(
        messages=messages,
        llm_provider=provider_enum,
        llm_model=model_str,
        organization_id=organization_id,
        db=db,
        temperature=0.3,
        max_tokens=PROMPT_SUGGESTION_MAX_TOKENS,
    )
    parsed = _extract_json_object(result["text"])
    overview, suggestions = _parse_suggestions(
        parsed,
        cluster_context,
        agent_prompt=imported_agent.content or "",
        flow_nodes=flow_nodes,
    )

    upsert_analysis_batch(
        db,
        evaluation_id=evaluation.id,
        job_kind=JOB_KIND_PROMPT_IMPROVEMENTS,
        job_run_id=job_run_id,
        batch_index=batch_index_base,
        payload={
            "metric_id": str(group.metric_id),
            "overview": overview,
            "suggestions": [s.model_dump(mode="json") for s in suggestions],
        },
    )

    completed_groups.add(str(group.metric_id))
    raw["completed_group_metric_ids"] = sorted(completed_groups)
    raw["completed_group_count"] = batch_index_base + 1
    raw["status"] = "running"
    raw["progress"] = _progress_for_groups(
        groups, completed_groups, total_metrics=total_metrics
    )
    evaluation.prompt_improvements = stamp_job_heartbeat(raw)
    flag_modified(evaluation, "prompt_improvements")
    if not keep_owned_header_write(
        db, evaluation, "prompt_improvements", job_run_id
    ):
        return "idle", None
    db.commit()
    if on_progress:
        on_progress(raw["progress"])
    return "continue", None
