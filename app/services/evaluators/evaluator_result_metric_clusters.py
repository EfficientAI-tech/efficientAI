"""Failure clustering for filtered evaluator-result scopes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import EvaluatorResult, EvaluatorResultClusterJob, Metric
from app.models.enums import EvaluatorResultStatus
from app.models.schemas import CallImportMetricAggregate, MetricFailurePolicy
from app.services.call_import_metric_clusters import (
    METRIC_CLUSTERS_CANCELLED_BY_USER_ERROR,
    _metric_is_quality,
    filter_completed_source_rows,
    list_eligible_cluster_source_rows,
    metric_clusters_raw_is_cancelled,
    metric_clusters_state_from_raw,
    metric_clusters_state_to_db,
)
from app.services.evaluators.evaluator_results_aggregate import compute_evaluator_results_aggregate
from app.services.evaluators.evaluator_results_query import (
    build_evaluator_results_query,
    classify_display_status,
)
from app.services.metric_cluster_rows import (
    MetricClusterSourceRow,
    build_evaluator_results_scope_key,
    evaluator_result_to_cluster_row,
)
from app.services.metric_failure_policy import (
    build_failure_policy_previews,
    effective_policies_from_raw,
    has_clusterable_metrics_from_scores,
    merge_failure_policies_into_raw,
    policies_from_evaluation_raw,
    validate_failure_policies_for_metrics,
)


def get_or_create_cluster_job(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    agent_id: Optional[UUID] = None,
    suite_id: Optional[UUID] = None,
    scenario_id: Optional[UUID] = None,
) -> EvaluatorResultClusterJob:
    scope_key = build_evaluator_results_scope_key(
        agent_id=agent_id,
        suite_id=suite_id,
        scenario_id=scenario_id,
    )
    job = (
        db.query(EvaluatorResultClusterJob)
        .filter(
            EvaluatorResultClusterJob.organization_id == organization_id,
            EvaluatorResultClusterJob.workspace_id == workspace_id,
            EvaluatorResultClusterJob.scope_key == scope_key,
        )
        .first()
    )
    if job is not None:
        return job
    job = EvaluatorResultClusterJob(
        organization_id=organization_id,
        workspace_id=workspace_id,
        scope_key=scope_key,
        agent_id=agent_id,
        suite_id=suite_id,
        scenario_id=scenario_id,
    )
    db.add(job)
    db.flush()
    return job


def load_completed_evaluator_results(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    agent_id: Optional[UUID] = None,
    suite_id: Optional[UUID] = None,
    scenario_id: Optional[UUID] = None,
) -> List[EvaluatorResult]:
    query = build_evaluator_results_query(
        db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=str(agent_id) if agent_id else None,
        suite_id=str(suite_id) if suite_id else None,
        scenario_id=str(scenario_id) if scenario_id else None,
        playground=False,
    )
    rows = query.all()
    from app.services.live_entity_storage import hydrate_evaluator_results

    hydrate_evaluator_results(rows)
    completed: List[EvaluatorResult] = []
    for row in rows:
        if classify_display_status(row) == EvaluatorResultStatus.COMPLETED.value:
            completed.append(row)
    return completed


def _metrics_for_ids(db: Session, organization_id: UUID, metric_ids: Sequence[UUID]) -> List[Metric]:
    if not metric_ids:
        return []
    return (
        db.query(Metric)
        .filter(
            Metric.organization_id == organization_id,
            Metric.id.in_(list(metric_ids)),
        )
        .all()
    )


def _child_names_by_parent(
    db: Session,
    organization_id: UUID,
    parent_ids: Sequence[UUID],
) -> Dict[str, List[str]]:
    if not parent_ids:
        return {}
    children = (
        db.query(Metric)
        .filter(
            Metric.organization_id == organization_id,
            Metric.parent_metric_id.in_(list(parent_ids)),
        )
        .all()
    )
    out: Dict[str, List[str]] = {}
    for child in children:
        if not child.parent_metric_id:
            continue
        key = str(child.parent_metric_id)
        out.setdefault(key, []).append(child.name)
    for key in out:
        out[key] = sorted(out[key])
    return out


def metrics_for_evaluator_result_clustering(
    db: Session,
    *,
    organization_id: UUID,
    results: Sequence[EvaluatorResult],
) -> List[Metric]:
    aggregate_metric_ids: List[UUID] = []
    seen: set[UUID] = set()
    for result in results:
        scores = result.metric_scores if isinstance(result.metric_scores, dict) else {}
        for metric_id_str in scores.keys():
            try:
                metric_id = UUID(metric_id_str)
            except ValueError:
                continue
            if metric_id in seen:
                continue
            seen.add(metric_id)
            aggregate_metric_ids.append(metric_id)

    if not aggregate_metric_ids:
        return []

    aggregate_metrics = _metrics_for_ids(db, organization_id, aggregate_metric_ids)
    by_id = {metric.id: metric for metric in aggregate_metrics}

    normalized_ids: List[UUID] = []
    normalized_seen: set[UUID] = set()
    for metric_id in aggregate_metric_ids:
        metric = by_id.get(metric_id)
        target_id = (
            metric.parent_metric_id
            if metric is not None and metric.parent_metric_id
            else metric_id
        )
        if target_id in normalized_seen:
            continue
        normalized_seen.add(target_id)
        normalized_ids.append(target_id)

    metrics = _metrics_for_ids(db, organization_id, normalized_ids)
    return [
        metric
        for metric in metrics
        if getattr(metric, "enabled", True) and _metric_is_quality(metric)
    ]


def compute_aggregates_for_evaluator_results(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    agent_id: Optional[UUID] = None,
    suite_id: Optional[UUID] = None,
    scenario_id: Optional[UUID] = None,
) -> Tuple[List[CallImportMetricAggregate], int]:
    """Return metric aggregates and completed row count for a filter scope."""
    if suite_id is not None:
        agg = compute_evaluator_results_aggregate(
            db,
            organization_id=organization_id,
            workspace_id=workspace_id,
            suite_id=suite_id,
            agent_id=agent_id,
            scenario_id=scenario_id,
        )
        return list(agg.metrics), agg.completed_rows

    if agent_id is not None and scenario_id is not None:
        agg = compute_evaluator_results_aggregate(
            db,
            organization_id=organization_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            scenario_id=scenario_id,
        )
        return list(agg.metrics), agg.completed_rows

    results = load_completed_evaluator_results(
        db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        suite_id=suite_id,
        scenario_id=scenario_id,
    )
    metrics = metrics_for_evaluator_result_clustering(
        db, organization_id=organization_id, results=results
    )
    metric_ids = [m.id for m in metrics]
    if not metric_ids:
        return [], len(results)

    # Reuse aggregate builder via a synthetic narrow scope when possible.
    if agent_id and not suite_id and not scenario_id and results:
        scenario_ids = {r.scenario_id for r in results if r.scenario_id}
        if len(scenario_ids) == 1:
            only_scenario = next(iter(scenario_ids))
            agg = compute_evaluator_results_aggregate(
                db,
                organization_id=organization_id,
                workspace_id=workspace_id,
                agent_id=agent_id,
                scenario_id=only_scenario,
            )
            return list(agg.metrics), agg.completed_rows

    # Workspace-wide or mixed scope: build aggregates from loaded rows inline.
    from collections import defaultdict

    from app.models.schemas import CallImportMetricHistogramBucket, CallImportMetricValueCount

    metric_values: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "numeric": [],
            "categories": defaultdict(int),
            "count": 0,
            "skipped": 0,
            "errors": 0,
            "name": None,
            "type": None,
        }
    )
    for row in results:
        scores = row.metric_scores if isinstance(row.metric_scores, dict) else {}
        for metric_id_str, entry in scores.items():
            if not isinstance(entry, dict):
                continue
            bucket = metric_values[metric_id_str]
            bucket["count"] += 1
            if entry.get("metric_name"):
                bucket["name"] = entry.get("metric_name")
            if entry.get("type"):
                bucket["type"] = entry.get("type")
            if entry.get("skipped"):
                bucket["skipped"] += 1
                continue
            if entry.get("error"):
                bucket["errors"] += 1
                continue
            value = entry.get("value")
            mtype = (entry.get("type") or "").lower()
            if mtype in ("number", "rating") and isinstance(value, (int, float)):
                bucket["numeric"].append(float(value))
            elif mtype == "boolean":
                label = "true" if value in (True, "true", 1, "1") else "false"
                bucket["categories"][label] += 1
            else:
                text = str(value) if value is not None else "—"
                bucket["categories"][text] += 1

    metric_meta = {str(m.id): m for m in metrics}
    aggregates: List[CallImportMetricAggregate] = []
    for metric_id_str, data in sorted(metric_values.items(), key=lambda kv: kv[0]):
        meta = metric_meta.get(metric_id_str)
        numeric = data["numeric"]
        value_counts = [
            CallImportMetricValueCount(label=label, count=count)
            for label, count in sorted(data["categories"].items())
        ]
        aggregates.append(
            CallImportMetricAggregate(
                metric_id=metric_id_str,
                metric_name=data["name"] or (meta.name if meta else metric_id_str),
                metric_type=data["type"] or (meta.metric_type if meta else None),
                metric_category=getattr(meta, "metric_category", "quality") if meta else "quality",
                count=data["count"],
                skipped=data["skipped"],
                errors=data["errors"],
                mean=sum(numeric) / len(numeric) if numeric else None,
                value_counts=value_counts,
                histogram=[],
            )
        )
    return aggregates, len(results)


def clustering_context_for_job(
    db: Session,
    job: EvaluatorResultClusterJob,
) -> Tuple[
    List[Metric],
    List[CallImportMetricAggregate],
    Dict[str, MetricFailurePolicy],
    Literal["inferred", "user"],
    Dict[str, List[str]],
    List[MetricClusterSourceRow],
    int,
]:
    results = load_completed_evaluator_results(
        db,
        organization_id=job.organization_id,
        workspace_id=job.workspace_id,
        agent_id=job.agent_id,
        suite_id=job.suite_id,
        scenario_id=job.scenario_id,
    )
    source_rows = [evaluator_result_to_cluster_row(r) for r in results]
    metrics = metrics_for_evaluator_result_clustering(
        db, organization_id=job.organization_id, results=results
    )
    aggregates, completed_count = compute_aggregates_for_evaluator_results(
        db,
        organization_id=job.organization_id,
        workspace_id=job.workspace_id,
        agent_id=job.agent_id,
        suite_id=job.suite_id,
        scenario_id=job.scenario_id,
    )
    parent_ids = [
        m.id
        for m in metrics
        if getattr(m, "selection_mode", None) and not getattr(m, "parent_metric_id", None)
    ]
    child_names_by_parent = _child_names_by_parent(
        db, job.organization_id, parent_ids
    )
    policies, source = effective_policies_from_raw(
        job.metric_clusters,
        metrics,
        aggregates,
        child_names_by_parent=child_names_by_parent,
    )
    return metrics, aggregates, policies, source, child_names_by_parent, source_rows, completed_count


def metric_clusters_payload(job: EvaluatorResultClusterJob) -> Optional[Any]:
    if job.metric_clusters is None:
        return None
    completed = 0
    # Stale detection uses stored completed count when present.
    raw = job.metric_clusters if isinstance(job.metric_clusters, dict) else {}
    if isinstance(raw, dict):
        completed = int(raw.get("generated_at_completed_rows") or 0)
    return metric_clusters_state_from_raw(job.metric_clusters, completed_rows=completed)


def resolve_source_row_selection(
    db: Session,
    job: EvaluatorResultClusterJob,
    *,
    evaluation_row_ids: Optional[List[UUID]] = None,
    row_limit: Optional[int] = None,
    policies: Optional[Dict[str, MetricFailurePolicy]] = None,
) -> Tuple[List[MetricClusterSourceRow], List[str]]:
    metrics, _aggregates, default_policies, _source, _child_map, source_rows, _ = (
        clustering_context_for_job(db, job)
    )
    active_policies = policies or default_policies
    eligible = list_eligible_cluster_source_rows(source_rows, metrics, active_policies)
    eligible_ordered_ids = [str(item["evaluation_row_id"]) for item in eligible]
    eligible_id_set = set(eligible_ordered_ids)

    if evaluation_row_ids is None and row_limit is not None:
        selected_ids = eligible_ordered_ids[:row_limit]
        filtered = filter_completed_source_rows(
            source_rows, [UUID(rid) for rid in selected_ids]
        )
        return filtered, selected_ids

    if evaluation_row_ids is None:
        selected_ids = eligible_ordered_ids
        filtered = filter_completed_source_rows(
            source_rows, [UUID(rid) for rid in selected_ids]
        )
        return filtered, selected_ids

    requested = {str(rid) for rid in evaluation_row_ids}
    completed_id_set = {str(row.row_id) for row in source_rows}
    unknown = sorted(requested - completed_id_set)
    if unknown:
        raise ValueError(
            "One or more evaluation_row_ids are missing or not completed: "
            + ", ".join(unknown[:5])
            + ("…" if len(unknown) > 5 else "")
        )
    not_eligible = sorted(requested - eligible_id_set)
    if not_eligible:
        raise ValueError(
            "Each selected row must have at least one flagged quality metric. "
            "Ineligible row(s): "
            + ", ".join(not_eligible[:5])
            + ("…" if len(not_eligible) > 5 else "")
        )
    selected_ids = sorted(requested)
    filtered = filter_completed_source_rows(source_rows, evaluation_row_ids)
    return filtered, selected_ids


def has_clusterable_evaluator_results(
    db: Session,
    job: EvaluatorResultClusterJob,
    policies: Dict[str, MetricFailurePolicy],
) -> bool:
    results = load_completed_evaluator_results(
        db,
        organization_id=job.organization_id,
        workspace_id=job.workspace_id,
        agent_id=job.agent_id,
        suite_id=job.suite_id,
        scenario_id=job.scenario_id,
    )
    metrics = metrics_for_evaluator_result_clustering(
        db, organization_id=job.organization_id, results=results
    )

    class _RowShim:
        def __init__(self, result: EvaluatorResult):
            self.status = "completed"
            self.metric_scores = result.metric_scores

    return has_clusterable_metrics_from_scores(
        metrics,
        policies,
        [_RowShim(r) for r in results],
    )


def apply_metric_clusters_cancel(job: EvaluatorResultClusterJob) -> bool:
    raw = job.metric_clusters
    if not isinstance(raw, dict):
        return False
    if (raw.get("status") or "").lower() != "running":
        return False
    progress = raw.get("progress") if isinstance(raw.get("progress"), dict) else {}
    job.metric_clusters = {
        **raw,
        "status": "cancelled",
        "error_message": METRIC_CLUSTERS_CANCELLED_BY_USER_ERROR,
        "progress": progress,
        "celery_task_id": None,
    }
    return True


def failure_policies_response_for_job(db: Session, job: EvaluatorResultClusterJob):
    metrics, aggregates, policies, source, child_names_by_parent, _rows, _ = (
        clustering_context_for_job(db, job)
    )
    previews = build_failure_policy_previews(
        metrics,
        aggregates,
        child_names_by_parent=child_names_by_parent,
        effective=policies,
    )
    updated_at = None
    raw_mc = job.metric_clusters
    if isinstance(raw_mc, dict) and raw_mc.get("failure_policies_updated_at"):
        try:
            updated_at = datetime.fromisoformat(str(raw_mc["failure_policies_updated_at"]))
        except ValueError:
            updated_at = None
    from app.models.schemas import MetricFailurePoliciesResponse

    return MetricFailurePoliciesResponse(
        previews=previews,
        policies=policies,
        source=source,
        updated_at=updated_at,
    )
