"""Per-metric success rules for Harbor simulation runs."""

from __future__ import annotations

from typing import Any, Iterable, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import Metric
from app.models.schemas import MetricSuccessCriterion
from app.services.classification_metric_scores import classification_facets_from_entry
from app.services.metric_classification_validation import is_classification_metric
from app.services.metric_failure_policy import normalize_label
from app.services.metrics.option_labels import (
    classification_choice_labels_from_config,
    classification_score_labels_from_config,
    enum_labels_equal,
    enum_option_labels_from_config,
)


def _is_categorization_parent(metric: Metric) -> bool:
    return bool(metric.selection_mode and not metric.parent_metric_id)


def infer_criterion_kind(metric: Metric) -> str:
    if is_classification_metric(custom_data_type=metric.custom_data_type):
        return "classification"
    if _is_categorization_parent(metric):
        mode = (metric.selection_mode or "").lower()
        return "category_multi" if mode == "multi_label" else "category_single"
    if (metric.custom_data_type or "").lower() == "enum":
        return "enum"
    mtype = (metric.metric_type or "").lower()
    if mtype in ("boolean", "rating", "number", "text"):
        return mtype
    return "text"


def _coerce_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "yes", "1"):
            return True
        if lowered in ("false", "no", "0"):
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _bool_matches_success(value: Any, success_when: str) -> bool:
    b = _coerce_bool(value)
    if b is None:
        return False
    want_true = success_when == "yes"
    return b is want_true


def _numeric_compare(value: Any, op: str, threshold: float) -> bool:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False
    if op == "lt":
        return v < threshold
    if op == "lte":
        return v <= threshold
    if op == "gt":
        return v > threshold
    if op == "gte":
        return v >= threshold
    return False


def _entry_failed(entry: Optional[dict[str, Any]]) -> bool:
    if not isinstance(entry, dict):
        return True
    if entry.get("error") or entry.get("skipped"):
        return True
    if entry.get("value") is None and entry.get("type") != "category":
        return True
    return False


def criterion_passes(
    criterion: dict[str, Any] | MetricSuccessCriterion,
    *,
    metric_scores: dict[str, Any],
    metric: Metric,
    children_by_parent: dict[str, list[Metric]],
) -> bool:
    if isinstance(criterion, MetricSuccessCriterion):
        crit = criterion.model_dump(mode="json")
    else:
        crit = dict(criterion)
    kind = crit.get("kind")
    mid = str(crit.get("metric_id") or metric.id)
    entry = metric_scores.get(mid)

    if kind == "text":
        return True

    if kind == "boolean":
        if _entry_failed(entry):
            return False
        return _bool_matches_success(entry.get("value"), crit.get("success_when") or "yes")

    if kind in ("rating", "number"):
        if _entry_failed(entry):
            return False
        threshold = float(crit.get("threshold", 0))
        return _numeric_compare(entry.get("value"), crit.get("op") or "gte", threshold)

    if kind == "enum":
        if _entry_failed(entry):
            return False
        raw = entry.get("value")
        if raw is None:
            return False
        allowed = crit.get("success_values") or []
        return any(enum_labels_equal(str(raw), v) for v in allowed)

    if kind == "category_single":
        if _entry_failed(entry):
            return False
        chosen = entry.get("chosen_child_name") or entry.get("value")
        if chosen is None:
            return False
        allowed = {normalize_label(v) for v in (crit.get("success_values") or [])}
        return normalize_label(str(chosen)) in allowed

    if kind == "category_multi":
        rules = crit.get("label_rules") or []
        if not rules:
            return False
        for rule in rules:
            child_id = str(rule.get("child_id"))
            child_entry = metric_scores.get(child_id)
            if _entry_failed(child_entry):
                return False
            expect = rule.get("expect") or "yes"
            if not _bool_matches_success(child_entry.get("value"), expect):
                return False
        return True

    if kind == "classification":
        if _entry_failed(entry):
            return False
        questions = crit.get("questions") or {}
        if not questions:
            return False
        facets = classification_facets_from_entry(entry)
        used_any = False
        noul = questions.get("noul")
        if noul:
            used_any = True
            yes_no = facets.get("yes_no")
            if yes_no is None:
                return False
            if not _bool_matches_success(yes_no, noul.get("success_when") or "yes"):
                return False
        choice = questions.get("choice")
        if choice:
            used_any = True
            val = facets.get("choice")
            if not val:
                return False
            success_vals = choice.get("success_values") or []
            if not any(enum_labels_equal(val, v) for v in success_vals):
                return False
        score_q = questions.get("score")
        if score_q:
            used_any = True
            level = facets.get("level")
            if not level:
                return False
            success_vals = score_q.get("success_values") or []
            if not any(enum_labels_equal(level, v) for v in success_vals):
                return False
        return used_any

    return False


def is_gating_criterion(criterion: dict[str, Any] | MetricSuccessCriterion) -> bool:
    kind = criterion.get("kind") if isinstance(criterion, dict) else criterion.kind
    return kind != "text"


def apply_success_criteria(
    metric_scores: dict[str, Any],
    criteria: Iterable[dict[str, Any] | MetricSuccessCriterion],
    metrics_by_id: dict[str, Metric],
    children_by_parent: dict[str, list[Metric]],
) -> tuple[bool, Optional[float], dict[str, Any]]:
    """Return ``(trial_passed, reward_fraction, updated_metric_scores)``."""
    updated = dict(metric_scores)
    gating: list[tuple[dict[str, Any], bool]] = []

    for raw in criteria:
        crit = raw if isinstance(raw, dict) else raw.model_dump(mode="json")
        mid = str(crit.get("metric_id"))
        metric = metrics_by_id.get(mid)
        if metric is None:
            continue
        passed = criterion_passes(
            crit,
            metric_scores=updated,
            metric=metric,
            children_by_parent=children_by_parent,
        )
        if not is_gating_criterion(crit):
            continue
        gating.append((crit, passed))
        entry = updated.get(mid)
        if isinstance(entry, dict):
            entry = dict(entry)
            entry["passed"] = passed
            updated[mid] = entry
        kind = crit.get("kind")
        if kind == "category_multi":
            parent_entry = updated.get(mid)
            if isinstance(parent_entry, dict):
                parent_copy = dict(parent_entry)
                parent_copy["passed"] = passed
                updated[mid] = parent_copy
            for rule in crit.get("label_rules") or []:
                child_id = str(rule.get("child_id"))
                child_entry = updated.get(child_id)
                child_ok = not _entry_failed(child_entry) and _bool_matches_success(
                    child_entry.get("value") if isinstance(child_entry, dict) else None,
                    rule.get("expect") or "yes",
                )
                if isinstance(child_entry, dict):
                    child_copy = dict(child_entry)
                    child_copy["passed"] = child_ok
                    updated[child_id] = child_copy

    if not gating:
        return False, None, updated
    n_pass = sum(1 for _, ok in gating if ok)
    reward = round(n_pass / len(gating), 4)
    trial_passed = n_pass == len(gating)
    return trial_passed, reward, updated


def _load_metric_context(
    db: Session,
    organization_id: UUID,
    metric_ids: list[str],
) -> tuple[dict[str, Metric], dict[str, list[Metric]]]:
    ids = [UUID(mid) for mid in metric_ids]
    metrics = (
        db.query(Metric)
        .filter(Metric.organization_id == organization_id, Metric.id.in_(ids))
        .all()
    )
    by_id = {str(m.id): m for m in metrics}
    parent_ids = [m.id for m in metrics if _is_categorization_parent(m)]
    children_by_parent: dict[str, list[Metric]] = {}
    if parent_ids:
        children = (
            db.query(Metric)
            .filter(
                Metric.organization_id == organization_id,
                Metric.parent_metric_id.in_(parent_ids),
            )
            .all()
        )
        for child in children:
            children_by_parent.setdefault(str(child.parent_metric_id), []).append(child)
    return by_id, children_by_parent


def validate_metric_success_criteria(
    db: Session,
    *,
    organization_id: UUID,
    metric_ids: list[UUID],
    criteria: list[MetricSuccessCriterion],
) -> None:
    """Raise ValueError when rules do not match metrics or cannot gate a run."""
    from app.services.evaluators.evaluator_helpers import normalize_metric_ids_for_storage

    normalized_ids = normalize_metric_ids_for_storage(
        db, organization_id, [str(m) for m in metric_ids]
    )
    by_id, children_by_parent = _load_metric_context(db, organization_id, normalized_ids)
    if len(by_id) != len(set(normalized_ids)):
        raise ValueError("One or more metric_ids were not found")

    gating_kinds: list[str] = []
    for rule in criteria:
        mid = str(rule.metric_id)
        if mid not in by_id:
            raise ValueError(f"No metric found for criterion metric_id={mid}")
        metric = by_id[mid]
        expected_kind = infer_criterion_kind(metric)
        if rule.kind != expected_kind:
            raise ValueError(
                f"Metric '{metric.name}' expects success criteria kind '{expected_kind}', "
                f"got '{rule.kind}'"
            )
        _validate_rule_shape(rule, metric, children_by_parent.get(mid, []))
        if rule.kind != "text":
            gating_kinds.append(rule.kind)

    if not gating_kinds:
        raise ValueError("At least one non-text metric with success criteria is required")


def _validate_rule_shape(
    rule: MetricSuccessCriterion,
    metric: Metric,
    children: list[Metric],
) -> None:
    kind = rule.kind
    if kind == "boolean":
        if rule.success_when not in ("yes", "no"):
            raise ValueError(f"Boolean metric '{metric.name}' requires success_when yes or no")
        return
    if kind == "rating":
        if rule.op not in ("lt", "lte", "gt", "gte") or rule.threshold is None:
            raise ValueError(f"Rating metric '{metric.name}' requires op and threshold")
        if not 0 <= rule.threshold <= 1:
            raise ValueError(f"Rating threshold for '{metric.name}' must be between 0 and 1")
        return
    if kind == "number":
        if rule.op not in ("lt", "lte", "gt", "gte") or rule.threshold is None:
            raise ValueError(f"Number metric '{metric.name}' requires op and threshold")
        return
    if kind == "enum":
        options = _enum_options(metric)
        if not rule.success_values:
            raise ValueError(f"Enum metric '{metric.name}' requires at least one success value")
        unknown = [
            v
            for v in rule.success_values
            if not any(enum_labels_equal(v, o) for o in options)
        ]
        if unknown:
            raise ValueError(f"Enum metric '{metric.name}' has unknown success values: {unknown}")
        return
    if kind == "category_single":
        if not rule.success_values:
            raise ValueError(f"Category '{metric.name}' requires at least one success label")
        child_names = {normalize_label(c.name) for c in children}
        for val in rule.success_values:
            if normalize_label(val) not in child_names:
                raise ValueError(f"Category '{metric.name}' has unknown label '{val}'")
        return
    if kind == "category_multi":
        if not rule.label_rules:
            raise ValueError(f"Multi-label category '{metric.name}' requires label_rules")
        child_ids = {str(c.id) for c in children}
        for lr in rule.label_rules:
            if str(lr.child_id) not in child_ids:
                raise ValueError(f"Multi-label '{metric.name}' has unknown child_id")
            if lr.expect not in ("yes", "no"):
                raise ValueError(f"Multi-label '{metric.name}' label_rules need expect yes or no")
        return
    if kind == "classification":
        cfg = metric.custom_config or {}
        questions = rule.questions
        if questions is None:
            raise ValueError(f"Classification metric '{metric.name}' requires questions")
        used = 0
        if questions.noul and _classification_block_enabled(cfg, "noul"):
            used += 1
            if questions.noul.success_when not in ("yes", "no"):
                raise ValueError(f"Classification noul for '{metric.name}' needs success_when")
        if questions.choice and _classification_block_enabled(cfg, "choice"):
            used += 1
            opts = classification_choice_labels_from_config(cfg)
            if not questions.choice.success_values:
                raise ValueError(f"Classification choice for '{metric.name}' needs success_values")
            for val in questions.choice.success_values:
                if not any(enum_labels_equal(val, o) for o in opts):
                    raise ValueError(f"Classification choice unknown value '{val}'")
        if questions.score and _classification_block_enabled(cfg, "score"):
            used += 1
            levels = classification_score_labels_from_config(cfg)
            if not questions.score.success_values:
                raise ValueError(f"Classification score for '{metric.name}' needs success_values")
            for val in questions.score.success_values:
                if not any(enum_labels_equal(val, level) for level in levels):
                    raise ValueError(f"Classification score unknown level '{val}'")
        if used == 0:
            raise ValueError(
                f"Classification metric '{metric.name}' must use at least one enabled question"
            )
        return
    if kind == "text":
        return
    raise ValueError(f"Unknown success criteria kind '{kind}'")


def _classification_block_enabled(cfg: dict[str, Any], key: str) -> bool:
    block = cfg.get(key)
    return isinstance(block, dict) and bool(block.get("enabled"))


def _enum_options(metric: Metric) -> list[str]:
    return enum_option_labels_from_config(metric.custom_config or {})


def criteria_to_storage(criteria: list[MetricSuccessCriterion]) -> list[dict[str, Any]]:
    return [c.model_dump(mode="json") for c in criteria]
