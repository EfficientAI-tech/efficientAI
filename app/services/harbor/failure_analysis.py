"""Failure clusters and prompt suggestions for a finished simulation run.

Reuses the call-import clustering pipeline: a trial's metric counts as failed when it
missed the success rule the user set for the run (``metric_scores[mid]["passed"] is
False``). Runs without rules fall back to ``normalize_metric_score < pass_threshold``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import (
    Agent,
    EvaluatorResult,
    EvaluatorResultStatus,
    Metric,
    ModelProvider,
    Persona,
    Scenario,
    SimulationRun,
)
from app.models.schemas import (
    EvaluationMetricClustersState,
    EvaluationPromptImprovementsState,
)
from app.services.call_import_metric_clusters import (
    CancelCheck,
    FailurePredicate,
    ProgressCallback,
    generate_metric_clusters_for_source_rows,
)
from app.services.call_import_prompt_improvements import (
    generate_prompt_improvements_for_prompt,
)
from app.services.harbor.result_ingest import trial_results
from app.services.harbor.rewards import normalize_metric_score
from app.services.harbor.success_criteria import is_gating_criterion
from app.services.metric_cluster_rows import (
    MetricClusterSourceRow,
    evaluator_result_to_cluster_row,
)
from app.services.metric_clusters_rca_summary import format_failure_policy_reason
from app.services.testing.test_agent_simulation_prompt import (
    get_agent_base_prompt,
    is_chat_agent,
)

_OP_SYMBOLS = {"lt": "<", "lte": "≤", "gt": ">", "gte": "≥"}


def gating_criteria_by_metric(run: SimulationRun) -> dict[str, dict[str, Any]]:
    criteria = run.metric_success_criteria if isinstance(run.metric_success_criteria, list) else []
    return {
        str(c.get("metric_id")): c
        for c in criteria
        if isinstance(c, dict) and c.get("metric_id") and is_gating_criterion(c)
    }


def _child_names(db: Session, organization_id: UUID, parent_ids: list[UUID]) -> dict[str, str]:
    if not parent_ids:
        return {}
    children = (
        db.query(Metric)
        .filter(
            Metric.organization_id == organization_id,
            Metric.parent_metric_id.in_(parent_ids),
        )
        .all()
    )
    return {str(c.id): c.name for c in children}


def describe_success_rule(
    criterion: dict[str, Any],
    child_names: Optional[dict[str, str]] = None,
) -> str:
    """Human-readable success rule, e.g. ``score ≥ 0.8`` or ``one of: Resolved``."""
    kind = criterion.get("kind")
    if kind == "boolean":
        return f"answer is {criterion.get('success_when') or 'yes'}"
    if kind in ("rating", "number"):
        op = _OP_SYMBOLS.get(criterion.get("op") or "gte", criterion.get("op") or "")
        return f"score {op} {criterion.get('threshold')}"
    if kind in ("enum", "category_single"):
        values = ", ".join(str(v) for v in criterion.get("success_values") or [])
        return f"one of: {values}" if values else "allowed values"
    if kind == "category_multi":
        names = child_names or {}
        rules = [
            f"{names.get(str(r.get('child_id')), 'label')} = {r.get('expect') or 'yes'}"
            for r in criterion.get("label_rules") or []
            if isinstance(r, dict)
        ]
        return "; ".join(rules) if rules else "label rules"
    if kind == "classification":
        questions = criterion.get("questions") or {}
        parts = []
        if questions.get("noul"):
            parts.append(f"answer is {questions['noul'].get('success_when') or 'yes'}")
        for key in ("choice", "score"):
            if questions.get(key):
                values = ", ".join(str(v) for v in questions[key].get("success_values") or [])
                parts.append(f"{key} in: {values}")
        return "; ".join(parts) if parts else "classification rules"
    return "no rule"


def success_rule_labels(db: Session, run: SimulationRun) -> dict[str, str]:
    """``metric_id -> rule description`` for the run's gating success rules."""
    criteria = gating_criteria_by_metric(run)
    multi_parents = [
        UUID(mid) for mid, c in criteria.items() if c.get("kind") == "category_multi"
    ]
    child_names = _child_names(db, run.organization_id, multi_parents)
    return {mid: describe_success_rule(c, child_names) for mid, c in criteria.items()}


def simulation_failure_predicate(
    run: SimulationRun,
    metrics_by_id: dict[str, Metric],
) -> FailurePredicate:
    criteria = gating_criteria_by_metric(run)

    def _failed(row: MetricClusterSourceRow, metric: Metric) -> bool:
        mid = str(metric.id)
        entry = (row.metric_scores or {}).get(mid)
        if criteria:
            if mid not in criteria:
                return False
            # apply_success_criteria marks each gating metric entry with ``passed``.
            if isinstance(entry, dict) and entry.get("passed") is not None:
                return entry.get("passed") is False
            # Multi-label parents may only have child entries.
            return any(
                isinstance(child, dict)
                and str(child.get("parent_metric_id") or "") == mid
                and child.get("passed") is False
                for child in (row.metric_scores or {}).values()
            )
        if not isinstance(entry, dict):
            return False
        score = normalize_metric_score(entry, metrics_by_id.get(mid, metric))
        return score is not None and score < run.pass_threshold

    return _failed


def run_metrics_for_analysis(db: Session, run: SimulationRun, agent: Agent) -> list[Metric]:
    """Top-level metrics that can gate this run: rule metrics, else the run's scored metrics."""
    criteria = gating_criteria_by_metric(run)
    if criteria:
        return (
            db.query(Metric)
            .filter(
                Metric.organization_id == run.organization_id,
                Metric.id.in_([UUID(mid) for mid in criteria]),
            )
            .all()
        )
    from app.workers.tasks.process_evaluator_result import select_metrics_for_evaluation

    metrics = select_metrics_for_evaluation(
        db,
        organization_id=run.organization_id,
        agent=agent,
        metric_ids=run.metric_ids,
        workspace_id=run.workspace_id,
    )
    return [m for m in metrics if not m.parent_metric_id]


def trial_label(result: EvaluatorResult, scenario_name: str, persona_name: str) -> str:
    attempt = f" · attempt {result.attempt_index}" if result.attempt_index else ""
    return f"{scenario_name} · {persona_name}{attempt} (#{result.result_id})"


def simulation_cluster_rows(
    db: Session,
    run: SimulationRun,
) -> list[MetricClusterSourceRow]:
    """Completed trials as clustering rows, labelled by scenario · persona · attempt."""
    results = [
        r for r in trial_results(db, run.id) if r.status == EvaluatorResultStatus.COMPLETED.value
    ]
    scenario_ids = {r.scenario_id for r in results if r.scenario_id}
    persona_ids = {r.persona_id for r in results if r.persona_id}
    scenario_names = (
        {s.id: s.name for s in db.query(Scenario).filter(Scenario.id.in_(scenario_ids)).all()}
        if scenario_ids
        else {}
    )
    persona_names = (
        {p.id: p.name for p in db.query(Persona).filter(Persona.id.in_(persona_ids)).all()}
        if persona_ids
        else {}
    )
    rows = []
    for result in results:
        row = evaluator_result_to_cluster_row(result)
        rows.append(
            MetricClusterSourceRow(
                row_id=row.row_id,
                conversation_id=trial_label(
                    result,
                    scenario_names.get(result.scenario_id) or "Scenario",
                    persona_names.get(result.persona_id) or "Persona",
                ),
                row_index=result.attempt_index,
                metric_scores=row.metric_scores,
                status=EvaluatorResultStatus.COMPLETED.value,
                transcript=row.transcript,
            )
        )
    return rows


def count_failed_trials(db: Session, run: SimulationRun) -> int:
    return sum(
        1
        for r in trial_results(db, run.id)
        if r.status == EvaluatorResultStatus.COMPLETED.value and r.passed is False
    )


def editable_agent_prompt(agent: Agent) -> str:
    """The prompt the user maintains for the production agent (before simulation wrapping)."""
    if is_chat_agent(agent):
        provider = (agent.provider_prompt or "").strip()
        if provider:
            return provider
    return get_agent_base_prompt(agent)


def _label_failure_reasons(
    state: EvaluationMetricClustersState,
    rule_labels: dict[str, str],
) -> None:
    """Replace the generic policy text with the success rule each trial missed."""
    for group in state.groups:
        rule = rule_labels.get(group.metric_id)
        if not rule:
            continue
        group.failure_reason = f"Missed success rule: {rule}"
        for cluster in group.clusters:
            gap = format_failure_policy_reason(None, None, gap_label=cluster.gap_label)
            cluster.failure_reason = f"Missed success rule: {rule}. {gap}"


def generate_simulation_metric_clusters(
    db: Session,
    run: SimulationRun,
    *,
    provider: ModelProvider,
    model: str,
    on_progress: Optional[ProgressCallback] = None,
    max_llm_calls: Optional[int] = None,
    is_cancelled: Optional[CancelCheck] = None,
) -> EvaluationMetricClustersState:
    agent = db.query(Agent).filter(Agent.id == run.agent_id).one()
    metrics = run_metrics_for_analysis(db, run, agent)
    metrics_by_id = {str(m.id): m for m in metrics}
    source_rows = simulation_cluster_rows(db, run)
    state = generate_metric_clusters_for_source_rows(
        db,
        job_key=run.id,
        metric_clusters_raw=None,
        completed_row_count=len(source_rows),
        organization_id=run.organization_id,
        provider=provider,
        model=model,
        source_rows=source_rows,
        metrics=metrics,
        policies={},
        on_progress=on_progress,
        max_llm_calls=max_llm_calls,
        is_cancelled=is_cancelled,
        failure_predicate=simulation_failure_predicate(run, metrics_by_id),
    )
    if state.status == "failed" and not state.groups and state.error_message:
        if state.error_message.startswith("No flagged calls"):
            state.error_message = (
                "No completed trial missed a success rule, so there is nothing to cluster."
            )
    _label_failure_reasons(state, success_rule_labels(db, run))
    return state


def generate_simulation_prompt_improvements(
    db: Session,
    run: SimulationRun,
    clusters_state: EvaluationMetricClustersState,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    credential_id: Optional[UUID] = None,
) -> dict[str, Any]:
    """Prompt suggestions for the production agent, stored with the base prompt they target."""
    agent = db.query(Agent).filter(Agent.id == run.agent_id).one()
    base_prompt = editable_agent_prompt(agent)
    state = generate_prompt_improvements_for_prompt(
        agent_id=str(agent.id),
        agent_name=agent.name,
        agent_prompt=base_prompt,
        agent_flowchart=None,
        clusters_state=clusters_state,
        completed_rows=clusters_state.generated_at_completed_rows,
        organization_id=run.organization_id,
        db=db,
        provider=provider,
        model=model,
        credential_id=credential_id,
    )
    raw = state.model_dump(mode="json")
    raw["compose_base_prompt"] = base_prompt
    return raw


def failed_prompt_improvements(message: str) -> dict[str, Any]:
    return EvaluationPromptImprovementsState(
        status="failed",
        error_message=message[:500],
        generated_at=datetime.now(timezone.utc),
    ).model_dump(mode="json")
