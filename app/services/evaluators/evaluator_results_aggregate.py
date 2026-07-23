"""Metric aggregates for evaluator result scopes (suite or agent+scenario)."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from statistics import mean, median, pstdev
from typing import Any, Dict, List, Optional
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
    if suite_id is None and (agent_id is None or scenario_id is None):
        raise ValueError("Provide suite_id or both agent_id and scenario_id")

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

    for row in scored_rows:
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

    metric_ids: List[UUID] = []
    for mid in metric_values.keys():
        try:
            metric_ids.append(UUID(mid))
        except ValueError:
            continue
    metrics_db = (
        db.query(Metric).filter(
            Metric.organization_id == organization_id,
            Metric.id.in_(metric_ids),
        ).all()
        if metric_ids
        else []
    )
    metric_meta = {str(m.id): m for m in metrics_db}

    aggregates: List[CallImportMetricAggregate] = []
    for metric_id_str, data in sorted(
        metric_values.items(),
        key=lambda item: (
            metric_meta.get(item[0]).name
            if metric_meta.get(item[0])
            else item[1]["name"] or item[0]
        ),
    ):
        meta = metric_meta.get(metric_id_str)
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

    scope_label = str(suite_id) if suite_id else f"{agent_id}:{scenario_id}"
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
