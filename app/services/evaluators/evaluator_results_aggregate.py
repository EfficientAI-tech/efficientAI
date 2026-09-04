"""Metric aggregates for evaluator result scopes (suite or agent+scenario)."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from statistics import mean, median, pstdev
from typing import Any, DefaultDict, Dict, List, Optional, Set
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import EvaluatorResult, Metric
from app.models.enums import EvaluatorResultStatus
from app.models.schemas import (
    CallImportMetricAggregate,
    CallImportMetricHistogramBucket,
    CallImportMetricValueCount,
    EvaluatorResultsAggregateResponse,
)
from app.services.evaluators.evaluator_results_query import (
    build_evaluator_results_query,
    classify_display_status,
)


def _numeric_histogram(values: List[float], buckets: int = 8) -> List[CallImportMetricHistogramBucket]:
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    if lo == hi:
        return [CallImportMetricHistogramBucket(x0=lo, x1=hi, count=len(values))]
    width = (hi - lo) / buckets
    counts = [0] * buckets
    for v in values:
        idx = min(buckets - 1, int((v - lo) / width) if width else 0)
        counts[idx] += 1
    out: List[CallImportMetricHistogramBucket] = []
    for i, count in enumerate(counts):
        if count == 0:
            continue
        start = lo + i * width
        end = lo + (i + 1) * width if i < buckets - 1 else hi
        out.append(CallImportMetricHistogramBucket(x0=start, x1=end, count=count))
    return out


def _percentile(sorted_vals: List[float], p: float) -> Optional[float]:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def _is_categorization_parent(metric: Optional[Metric]) -> bool:
    return bool(
        metric is not None
        and getattr(metric, "selection_mode", None)
        and not getattr(metric, "parent_metric_id", None)
    )


def _load_metric_registry(
    db: Session,
    organization_id: UUID,
    metric_id_strs: Set[str],
) -> Dict[str, Metric]:
    parsed: List[UUID] = []
    for mid in metric_id_strs:
        try:
            parsed.append(UUID(mid))
        except ValueError:
            continue
    if not parsed:
        return {}

    metrics = (
        db.query(Metric)
        .filter(
            Metric.organization_id == organization_id,
            Metric.id.in_(parsed),
        )
        .all()
    )
    registry: Dict[str, Metric] = {str(m.id): m for m in metrics}

    parent_ids = {
        str(m.parent_metric_id)
        for m in metrics
        if m.parent_metric_id is not None
    } - set(registry.keys())
    if parent_ids:
        parents = (
            db.query(Metric)
            .filter(
                Metric.organization_id == organization_id,
                Metric.id.in_([UUID(pid) for pid in parent_ids]),
            )
            .all()
        )
        for parent in parents:
            registry[str(parent.id)] = parent

    cat_parent_ids = [m.id for m in registry.values() if _is_categorization_parent(m)]
    if cat_parent_ids:
        children = (
            db.query(Metric)
            .filter(
                Metric.organization_id == organization_id,
                Metric.parent_metric_id.in_(cat_parent_ids),
            )
            .all()
        )
        for child in children:
            registry[str(child.id)] = child

    return registry


def _resolve_aggregate_id(metric_id_str: str, registry: Dict[str, Metric]) -> str:
    meta = registry.get(metric_id_str)
    if meta and meta.parent_metric_id:
        parent = registry.get(str(meta.parent_metric_id))
        if _is_categorization_parent(parent):
            return str(parent.id)
    return metric_id_str


def _labels_from_categorization_entry(entry: Dict[str, Any], meta: Metric) -> List[str]:
    mode = entry.get("selection_mode") or getattr(meta, "selection_mode", None)
    if mode == "multi_label":
        selected = entry.get("selected_child_names")
        if isinstance(selected, list):
            return [str(label).strip() for label in selected if str(label).strip()]
        return []
    chosen = entry.get("chosen_child_name") or entry.get("value")
    if chosen is not None and str(chosen).strip():
        return [str(chosen).strip()]
    return []


def _labels_from_child_booleans(
    scores: Dict[str, Any],
    parent_id: str,
    registry: Dict[str, Metric],
) -> List[str]:
    labels: List[str] = []
    for mid, meta in registry.items():
        if not meta.parent_metric_id or str(meta.parent_metric_id) != parent_id:
            continue
        entry = scores.get(mid)
        if not isinstance(entry, dict):
            continue
        if entry.get("skipped") or entry.get("error"):
            continue
        value = entry.get("value")
        if value in (True, "true", 1, "1"):
            labels.append(meta.name)
    parent = registry.get(parent_id)
    if parent and getattr(parent, "selection_mode", None) == "single_choice":
        return labels[:1]
    return labels


def _process_standalone_entry(
    bucket: Dict[str, Any],
    entry: Dict[str, Any],
) -> None:
    bucket["count"] += 1
    if entry.get("metric_name"):
        bucket["name"] = entry.get("metric_name")
    if entry.get("type"):
        bucket["type"] = entry.get("type")
    if entry.get("skipped"):
        bucket["skipped"] += 1
        return
    if entry.get("error"):
        bucket["errors"] += 1
        return

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


def compute_evaluator_results_aggregate(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    suite_id: Optional[UUID] = None,
    agent_id: Optional[UUID] = None,
    scenario_id: Optional[UUID] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> EvaluatorResultsAggregateResponse:
    query = build_evaluator_results_query(
        db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        suite_id=str(suite_id) if suite_id else None,
        agent_id=str(agent_id) if agent_id else None,
        scenario_id=str(scenario_id) if scenario_id else None,
        since=since,
        until=until,
    )
    rows = query.all()

    total_rows = len(rows)
    completed_rows = 0
    failed_rows = 0
    scored_rows: List[EvaluatorResult] = []

    for row in rows:
        display = classify_display_status(row)
        if display == EvaluatorResultStatus.COMPLETED.value:
            completed_rows += 1
            if row.metric_scores:
                scored_rows.append(row)
        elif display == EvaluatorResultStatus.FAILED.value:
            failed_rows += 1

    discovered_ids: Set[str] = set()
    for row in scored_rows:
        scores = row.metric_scores if isinstance(row.metric_scores, dict) else {}
        discovered_ids.update(str(mid) for mid in scores.keys())

    registry = _load_metric_registry(db, organization_id, discovered_ids)
    aggregate_ids = sorted(
        {_resolve_aggregate_id(mid, registry) for mid in discovered_ids}
    )

    metric_values: DefaultDict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "numeric": [],
            "categories": defaultdict(int),
            "count": 0,
            "skipped": 0,
            "errors": 0,
            "name": None,
            "type": None,
            "is_multi_label_parent": False,
        }
    )

    for row in scored_rows:
        scores = row.metric_scores if isinstance(row.metric_scores, dict) else {}
        for agg_id in aggregate_ids:
            meta = registry.get(agg_id)
            bucket = metric_values[agg_id]

            if _is_categorization_parent(meta):
                bucket["is_multi_label_parent"] = (
                    getattr(meta, "selection_mode", None) == "multi_label"
                )
                if meta and meta.name:
                    bucket["name"] = meta.name
                bucket["type"] = bucket["type"] or "category"

                entry = scores.get(agg_id)
                labels: List[str] = []
                row_touched = False

                if isinstance(entry, dict):
                    row_touched = True
                    if entry.get("metric_name"):
                        bucket["name"] = entry.get("metric_name")
                    if entry.get("skipped"):
                        bucket["skipped"] += 1
                        continue
                    if entry.get("error"):
                        bucket["errors"] += 1
                        continue
                    labels = _labels_from_categorization_entry(entry, meta)

                if not labels:
                    child_labels = _labels_from_child_booleans(scores, agg_id, registry)
                    if child_labels:
                        labels = child_labels
                        row_touched = True

                if not row_touched:
                    continue

                bucket["count"] += 1
                for label in labels:
                    bucket["categories"][label] += 1
                continue

            entry = scores.get(agg_id)
            if not isinstance(entry, dict):
                continue
            _process_standalone_entry(bucket, entry)

    aggregates: List[CallImportMetricAggregate] = []
    for metric_id_str, data in sorted(
        metric_values.items(),
        key=lambda item: (
            registry.get(item[0]).name
            if registry.get(item[0])
            else item[1]["name"] or item[0]
        ),
    ):
        meta = registry.get(metric_id_str)
        numeric: List[float] = data["numeric"]
        sorted_numeric = sorted(numeric)
        value_counts = [
            CallImportMetricValueCount(label=k, count=v)
            for k, v in sorted(data["categories"].items(), key=lambda x: -x[1])
        ][:20]
        hist = _numeric_histogram(sorted_numeric) if sorted_numeric else []
        aggregates.append(
            CallImportMetricAggregate(
                metric_id=metric_id_str,
                metric_name=(meta.name if meta else data["name"]) or metric_id_str,
                metric_type=(meta.metric_type if meta else data["type"]),
                is_multi_label_parent=bool(data["is_multi_label_parent"]),
                count=data["count"],
                skipped_count=data["skipped"],
                error_count=data["errors"],
                mean=mean(sorted_numeric) if sorted_numeric else None,
                median=median(sorted_numeric) if sorted_numeric else None,
                p25=_percentile(sorted_numeric, 0.25),
                p75=_percentile(sorted_numeric, 0.75),
                p95=_percentile(sorted_numeric, 0.95),
                min=min(sorted_numeric) if sorted_numeric else None,
                max=max(sorted_numeric) if sorted_numeric else None,
                stddev=pstdev(sorted_numeric) if len(sorted_numeric) > 1 else None,
                histogram_buckets=hist,
                value_counts=value_counts,
            )
        )

    if suite_id:
        scope_label = str(suite_id)
    elif agent_id and scenario_id:
        scope_label = f"{agent_id}:{scenario_id}"
    elif agent_id:
        scope_label = str(agent_id)
    else:
        scope_label = "workspace"
    return EvaluatorResultsAggregateResponse(
        scope=scope_label,
        suite_id=suite_id,
        agent_id=agent_id,
        scenario_id=scenario_id,
        total_rows=total_rows,
        completed_rows=completed_rows,
        failed_rows=failed_rows,
        metrics=aggregates,
    )
