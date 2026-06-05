"""Per-evaluation failure policies for clustering, PDF, and visualization flagged rates."""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence, Tuple

from app.models.database import (
    CallImportEvaluation,
    CallImportEvaluationRow,
    Metric,
)
from app.models.schemas import (
    CallImportMetricAggregate,
    MetricFailurePolicy,
    MetricFailurePolicyMetricPreview,
    MetricFailurePolicyValueCount,
    MetricFailurePoliciesResponse,
    MetricFailurePoliciesSaveRequest,
)

_NEGATIVE_LABEL_TOKENS = frozenset(
    {
        "no",
        "false",
        "fail",
        "failed",
        "bad",
        "missing",
        "not_detected",
        "not detected",
        "undetected",
        "incorrect",
        "wrong",
        "poor",
        "negative",
        "flagged",
    }
)

_BOOLEAN_LIKE_PAIRS: Tuple[Tuple[str, str], ...] = (
    ("yes", "no"),
    ("true", "false"),
    ("pass", "fail"),
    ("passed", "failed"),
    ("good", "bad"),
)


def normalize_label(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip().lower()


def _label_looks_negative(label: str) -> bool:
    normalized = normalize_label(label).replace("_", " ")
    if normalized in _NEGATIVE_LABEL_TOKENS:
        return True
    for token in _NEGATIVE_LABEL_TOKENS:
        if token in normalized.split():
            return True
    return False


def _pick_negative_from_pair(labels: Sequence[str]) -> Optional[str]:
    normalized = [normalize_label(l) for l in labels if normalize_label(l)]
    if len(normalized) != 2:
        return None
    for neg, pos in _BOOLEAN_LIKE_PAIRS:
        if set(normalized) == {neg, pos}:
            return neg
    return None


def _coerce_number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def suggest_failure_policy(
    metric: Metric,
    *,
    observed_labels: Sequence[str],
    child_names: Optional[Sequence[str]] = None,
    numeric_mean: Optional[float] = None,
) -> MetricFailurePolicy:
    metric_id = str(metric.id)
    selection_mode = (getattr(metric, "selection_mode", None) or "").lower()
    is_parent = bool(selection_mode and not getattr(metric, "parent_metric_id", None))

    if is_parent and selection_mode == "multi_label":
        children = [str(n).strip() for n in (child_names or []) if str(n).strip()]
        negative_children = [n for n in children if _label_looks_negative(n)]
        return MetricFailurePolicy(
            metric_id=metric_id,
            failure_values=[],
            failure_child_names=negative_children,
        )

    labels = [str(l).strip() for l in observed_labels if str(l).strip()]
    negative_labels = [l for l in labels if _label_looks_negative(l)]
    if negative_labels:
        return MetricFailurePolicy(
            metric_id=metric_id,
            failure_values=[normalize_label(l) for l in negative_labels],
        )

    pair_negative = _pick_negative_from_pair(labels)
    if pair_negative is not None:
        return MetricFailurePolicy(
            metric_id=metric_id,
            failure_values=[pair_negative],
        )

    if numeric_mean is not None and 0 <= numeric_mean <= 1:
        return MetricFailurePolicy(
            metric_id=metric_id,
            failure_values=[],
            numeric_rule={"op": "lt", "threshold": 0.5},
        )

    return MetricFailurePolicy(metric_id=metric_id, failure_values=[])


def _numeric_matches_rule(value: Any, rule: Optional[Dict[str, Any]]) -> bool:
    if not rule or not isinstance(rule, dict):
        return False
    number = _coerce_number(value)
    if number is None:
        return False
    op = str(rule.get("op") or "lt").lower()
    threshold = float(rule.get("threshold", 0.5))
    if op == "lt":
        return number < threshold
    if op == "lte":
        return number <= threshold
    if op == "gt":
        return number > threshold
    if op == "gte":
        return number >= threshold
    return number < threshold


def _value_in_failure_set(value: Any, failure_values: Sequence[str]) -> bool:
    if not failure_values:
        return False
    normalized_failures = {normalize_label(v) for v in failure_values}
    label = normalize_label(value)
    if label in normalized_failures:
        return True
    if isinstance(value, bool):
        return normalize_label(value) in normalized_failures
    return False


def score_matches_failure_policy(
    scores: Mapping[str, Any],
    metric: Metric,
    policy: MetricFailurePolicy,
) -> bool:
    """Return True when this row's score for ``metric`` matches the failure policy."""
    entry = scores.get(str(metric.id))
    if not isinstance(entry, dict):
        entry = None
    if isinstance(entry, dict) and (entry.get("skipped") or entry.get("error")):
        return False

    selection_mode = (getattr(metric, "selection_mode", None) or "").lower()
    is_parent = bool(selection_mode and not getattr(metric, "parent_metric_id", None))

    if is_parent and selection_mode == "single_choice":
        chosen = None
        if isinstance(entry, dict):
            chosen = entry.get("chosen_child_name") or entry.get("value")
        if chosen is not None and str(chosen).strip():
            return _value_in_failure_set(chosen, policy.failure_values)
        return False

    if is_parent and selection_mode == "multi_label":
        failure_children = {
            normalize_label(n) for n in (policy.failure_child_names or [])
        }
        if not failure_children:
            return False
        if isinstance(entry, dict):
            selected = entry.get("selected_child_names")
            if isinstance(selected, list):
                for name in selected:
                    if normalize_label(name) in failure_children:
                        return True
        for child_entry_raw in scores.values():
            if not isinstance(child_entry_raw, dict):
                continue
            if child_entry_raw.get("skipped") or child_entry_raw.get("error"):
                continue
            if str(child_entry_raw.get("parent_metric_id") or "") != str(metric.id):
                continue
            child_name = str(child_entry_raw.get("metric_name") or "").strip()
            if normalize_label(child_name) not in failure_children:
                continue
            if child_entry_raw.get("value") is True:
                return True
        return False

    value = entry.get("value") if isinstance(entry, dict) else None
    if value is None and isinstance(entry, dict):
        return False

    if policy.numeric_rule:
        return _numeric_matches_rule(value, policy.numeric_rule)

    if isinstance(value, bool):
        return _value_in_failure_set(value, policy.failure_values)

    number = _coerce_number(value)
    if number is not None and not policy.failure_values:
        if policy.numeric_rule:
            return _numeric_matches_rule(value, policy.numeric_rule)
        if 0 <= number <= 1:
            return number < 0.5

    return _value_in_failure_set(value, policy.failure_values)


def is_metric_failure(
    eval_row: CallImportEvaluationRow,
    metric: Metric,
    policy: MetricFailurePolicy,
) -> bool:
    scores = eval_row.metric_scores if isinstance(eval_row.metric_scores, dict) else {}
    return score_matches_failure_policy(scores, metric, policy)


def policies_from_evaluation_raw(raw: Any) -> Tuple[Dict[str, MetricFailurePolicy], str]:
    if not isinstance(raw, dict):
        return {}, "inferred"
    source = str(raw.get("failure_policies_source") or "inferred").lower()
    if source not in ("inferred", "user"):
        source = "inferred"
    policies_raw = raw.get("failure_policies")
    if not isinstance(policies_raw, dict):
        return {}, source
    policies: Dict[str, MetricFailurePolicy] = {}
    for metric_id, item in policies_raw.items():
        if isinstance(item, dict):
            try:
                policies[str(metric_id)] = MetricFailurePolicy.model_validate(item)
            except Exception:
                continue
    return policies, source


def build_inferred_policies(
    metrics: Sequence[Metric],
    aggregates: Sequence[CallImportMetricAggregate],
    *,
    child_names_by_parent: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, MetricFailurePolicy]:
    agg_by_id = {str(a.metric_id): a for a in aggregates}
    policies: Dict[str, MetricFailurePolicy] = {}
    for metric in metrics:
        agg = agg_by_id.get(str(metric.id))
        observed = (
            [vc.label for vc in (agg.value_counts or []) if vc.label]
            if agg
            else []
        )
        row_counts = (
            {vc.label: vc.count for vc in (agg.value_counts or []) if vc.label}
            if agg
            else {}
        )
        raw = suggest_failure_policy(
            metric,
            observed_labels=observed,
            child_names=(child_names_by_parent or {}).get(str(metric.id)),
            numeric_mean=agg.mean if agg else None,
        )
        policies[str(metric.id)] = prune_policy_to_observed_rows(
            raw, metric, row_counts
        )
    return policies


def effective_policies(
    evaluation: CallImportEvaluation,
    metrics: Sequence[Metric],
    aggregates: Sequence[CallImportMetricAggregate],
    *,
    child_names_by_parent: Optional[Dict[str, List[str]]] = None,
) -> Tuple[Dict[str, MetricFailurePolicy], Literal["inferred", "user"]]:
    stored, source = policies_from_evaluation_raw(evaluation.metric_clusters)
    if source == "user" and stored:
        return stored, "user"
    inferred = build_inferred_policies(
        metrics,
        aggregates,
        child_names_by_parent=child_names_by_parent,
    )
    if stored and source == "inferred":
        return stored, "inferred"
    return inferred, "inferred"


def policy_has_failure_criteria(policy: MetricFailurePolicy, metric: Metric) -> bool:
    selection_mode = (getattr(metric, "selection_mode", None) or "").lower()
    is_multi_parent = bool(
        selection_mode == "multi_label"
        and not getattr(metric, "parent_metric_id", None)
    )
    if is_multi_parent:
        return bool(policy.failure_child_names)
    if policy.numeric_rule:
        return True
    return bool(policy.failure_values)


def format_policy_summary(policy: MetricFailurePolicy, metric: Metric) -> str:
    selection_mode = (getattr(metric, "selection_mode", None) or "").lower()
    if selection_mode == "multi_label" and not getattr(metric, "parent_metric_id", None):
        names = policy.failure_child_names or []
        return ", ".join(names) if names else "none"
    if policy.numeric_rule and isinstance(policy.numeric_rule, dict):
        op = policy.numeric_rule.get("op", "lt")
        threshold = policy.numeric_rule.get("threshold", 0.5)
        return f"numeric {op} {threshold}"
    values = policy.failure_values or []
    return ", ".join(values) if values else "none"


def build_failure_policy_previews(
    metrics: Sequence[Metric],
    aggregates: Sequence[CallImportMetricAggregate],
    *,
    child_names_by_parent: Optional[Dict[str, List[str]]] = None,
    effective: Optional[Dict[str, MetricFailurePolicy]] = None,
) -> List[MetricFailurePolicyMetricPreview]:
    agg_by_id = {str(a.metric_id): a for a in aggregates}
    previews: List[MetricFailurePolicyMetricPreview] = []
    for metric in metrics:
        metric_id = str(metric.id)
        agg = agg_by_id.get(metric_id)
        row_count_by_value: Dict[str, int] = {}
        value_counts: List[MetricFailurePolicyValueCount] = []
        if agg:
            for vc in agg.value_counts or []:
                row_count_by_value[vc.label] = vc.count
                value_counts.append(
                    MetricFailurePolicyValueCount(label=vc.label, count=vc.count)
                )
        child_names = (child_names_by_parent or {}).get(metric_id) or []
        suggested_raw = suggest_failure_policy(
            metric,
            observed_labels=list(row_count_by_value.keys()),
            child_names=child_names,
            numeric_mean=agg.mean if agg else None,
        )
        suggested = prune_policy_to_observed_rows(
            suggested_raw, metric, row_count_by_value
        )
        current = (effective or {}).get(metric_id)
        if current is None:
            current = suggested
        previews.append(
            MetricFailurePolicyMetricPreview(
                metric_id=metric_id,
                metric_name=metric.name,
                metric_type=getattr(metric, "metric_type", None),
                selection_mode=getattr(metric, "selection_mode", None),
                is_multi_label_parent=bool(
                    (getattr(metric, "selection_mode", None) or "").lower()
                    == "multi_label"
                    and not getattr(metric, "parent_metric_id", None)
                ),
                value_counts=value_counts,
                child_names=list(child_names),
                row_count_by_value=row_count_by_value,
                suggested_policy=suggested,
                effective_policy=current,
            )
        )
    return previews


def failure_policies_to_db(
    policies: Dict[str, MetricFailurePolicy],
    *,
    source: Literal["inferred", "user"],
) -> Dict[str, Any]:
    return {
        "failure_policies": {
            mid: p.model_dump(mode="json") for mid, p in policies.items()
        },
        "failure_policies_source": source,
        "failure_policies_updated_at": datetime.now(timezone.utc).isoformat(),
    }


def merge_failure_policies_into_raw(
    raw: Optional[Dict[str, Any]],
    policies: Dict[str, MetricFailurePolicy],
    *,
    source: Literal["inferred", "user"],
) -> Dict[str, Any]:
    base = dict(raw) if isinstance(raw, dict) else {}
    base.update(failure_policies_to_db(policies, source=source))
    return base


def failure_rate_percent_from_rows(
    eval_rows: Sequence[CallImportEvaluationRow],
    metric: Metric,
    policy: MetricFailurePolicy,
) -> Optional[float]:
    """Share of completed scored rows that match the failure policy (0–100)."""
    scored = 0
    failures = 0
    for eval_row in eval_rows:
        if eval_row.status != "completed":
            continue
        scores = (
            eval_row.metric_scores if isinstance(eval_row.metric_scores, dict) else {}
        )
        entry = scores.get(str(metric.id))
        if not isinstance(entry, dict):
            continue
        if entry.get("skipped") or entry.get("error"):
            continue
        scored += 1
        if is_metric_failure(eval_row, metric, policy):
            failures += 1
    if scored <= 0:
        return None
    return (failures / scored) * 100.0


def aggregate_primary_percent(
    raw: dict[str, Any],
    policy: Optional[MetricFailurePolicy] = None,
) -> Optional[float]:
    """Flagged/failure rate percent from an aggregate payload + optional policy."""
    if policy is None:
        mean = raw.get("mean")
        if isinstance(mean, (int, float)) and math.isfinite(float(mean)):
            value = float(mean)
            return value * 100 if 0 <= value <= 1 else max(0.0, min(value, 100.0))
        count = int(raw.get("count") or 0)
        value_counts = raw.get("value_counts")
        if count <= 0 or not isinstance(value_counts, list):
            return None
        flagged = 0
        for item in value_counts:
            if not isinstance(item, dict):
                continue
            label = normalize_label(item.get("label"))
            if label in _NEGATIVE_LABEL_TOKENS or label in {
                "fail",
                "failed",
                "bad",
                "true",
                "yes",
            }:
                flagged += int(item.get("count") or 0)
        return (flagged / count) * 100 if count else None

    if policy.numeric_rule:
        mean = raw.get("mean")
        if isinstance(mean, (int, float)) and math.isfinite(float(mean)):
            if _numeric_matches_rule(float(mean), policy.numeric_rule):
                return 100.0
            return 0.0

    count = int(raw.get("count") or 0)
    value_counts = raw.get("value_counts")
    if count <= 0 or not isinstance(value_counts, list):
        return None

    failure_values = {normalize_label(v) for v in policy.failure_values}
    failure_children = {normalize_label(n) for n in policy.failure_child_names}

    if raw.get("is_multi_label_parent") and failure_children:
        rows_with_failure = 0
        for item in value_counts:
            if not isinstance(item, dict):
                continue
            if normalize_label(item.get("label")) in failure_children:
                rows_with_failure += int(item.get("count") or 0)
        return min(100.0, (rows_with_failure / count) * 100) if count else None

    flagged = 0
    for item in value_counts:
        if not isinstance(item, dict):
            continue
        label = normalize_label(item.get("label"))
        if label in failure_values:
            flagged += int(item.get("count") or 0)
    return (flagged / count) * 100 if count else None


def prune_policy_to_observed_rows(
    policy: MetricFailurePolicy,
    metric: Metric,
    row_count_by_value: Mapping[str, int],
) -> MetricFailurePolicy:
    """Drop suggested failure labels that never appear in this evaluation."""
    selection_mode = (getattr(metric, "selection_mode", None) or "").lower()
    is_multi_parent = bool(
        selection_mode == "multi_label"
        and not getattr(metric, "parent_metric_id", None)
    )
    if is_multi_parent:
        kept = [
            name
            for name in (policy.failure_child_names or [])
            if (row_count_by_value.get(name) or 0) > 0
        ]
        return MetricFailurePolicy(
            metric_id=policy.metric_id,
            failure_values=[],
            failure_child_names=kept,
        )

    kept_values: List[str] = []
    for value in policy.failure_values or []:
        target = normalize_label(value)
        for label, count in row_count_by_value.items():
            if normalize_label(label) == target and count > 0:
                kept_values.append(target)
                break
    return MetricFailurePolicy(
        metric_id=policy.metric_id,
        failure_values=kept_values,
        failure_child_names=[],
        numeric_rule=policy.numeric_rule,
    )


def merge_clustering_policies(
    submitted: Optional[Dict[str, MetricFailurePolicy]],
    evaluation: CallImportEvaluation,
    metrics: Sequence[Metric],
    aggregates: Sequence[CallImportMetricAggregate],
    *,
    child_names_by_parent: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, MetricFailurePolicy]:
    """Build per-metric policies for clustering; submitted entries override inferred defaults."""
    effective, _source = effective_policies(
        evaluation,
        metrics,
        aggregates,
        child_names_by_parent=child_names_by_parent,
    )
    agg_by_id = {str(a.metric_id): a for a in aggregates}
    merged: Dict[str, MetricFailurePolicy] = {}
    for metric in metrics:
        mid = str(metric.id)
        agg = agg_by_id.get(mid)
        row_counts: Dict[str, int] = {}
        if agg:
            for vc in agg.value_counts or []:
                row_counts[vc.label] = vc.count
        if submitted is not None and mid in submitted:
            merged[mid] = submitted[mid]
            continue
        base = effective.get(mid) or suggest_failure_policy(
            metric,
            observed_labels=list(row_counts.keys()),
            child_names=(child_names_by_parent or {}).get(mid),
            numeric_mean=agg.mean if agg else None,
        )
        merged[mid] = prune_policy_to_observed_rows(base, metric, row_counts)
    return merged


def has_clusterable_metrics(
    metrics: Sequence[Metric],
    policies: Dict[str, MetricFailurePolicy],
    eval_rows: Sequence[CallImportEvaluationRow],
) -> bool:
    """True when at least one row matches a metric's active failure policy."""
    for eval_row in eval_rows:
        if eval_row.status != "completed":
            continue
        for metric in metrics:
            policy = policies.get(str(metric.id))
            if policy is None or not policy_has_failure_criteria(policy, metric):
                continue
            if is_metric_failure(eval_row, metric, policy):
                return True
    return False


def validate_failure_policies_for_metrics(
    policies: Dict[str, MetricFailurePolicy],
    metrics: Sequence[Metric],
) -> None:
    """Raise ValueError only for unknown metric ids in ``policies``.

    Empty failure criteria are allowed — those metrics are skipped during clustering.
    """
    metric_by_id = {str(m.id): m for m in metrics}
    errors: List[str] = []
    for metric_id in policies.keys():
        if metric_id not in metric_by_id:
            errors.append(f"Unknown metric_id {metric_id}")
    if errors:
        raise ValueError("; ".join(errors[:8]) + ("…" if len(errors) > 8 else ""))
