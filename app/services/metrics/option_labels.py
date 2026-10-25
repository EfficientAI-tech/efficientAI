"""Normalize metric enum / classification option shapes from DB or LLM."""

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional


def _scalar_option_to_string(val: Any) -> Optional[str]:
    if val is None:
        return None
    if isinstance(val, str):
        stripped = val.strip()
        return stripped or None
    if isinstance(val, bool):
        return str(val).strip() or None
    if isinstance(val, int):
        return str(val)
    if isinstance(val, float):
        if val == int(val):
            return str(int(val))
        text = str(val).strip()
        return text or None
    return None


def coerce_metric_option_label(opt: Any) -> Optional[str]:
    if isinstance(opt, dict):
        for key in ("value", "label", "name", "description"):
            if key not in opt:
                continue
            label = _scalar_option_to_string(opt.get(key))
            if label is not None:
                return label
        return None
    return _scalar_option_to_string(opt)


def enum_labels_equal(a: str, b: str) -> bool:
    """Strict label equality for pass/fail rules (case-insensitive, no numeric aliasing)."""
    return a.strip().lower() == b.strip().lower()


def _is_integer_label(label: str) -> bool:
    return bool(re.fullmatch(r"-?\d+", label.strip()))


def _numeric_option_same(candidate: str, option: str) -> bool:
    """Whether ``candidate`` can refer to ``option`` when strings differ only numerically."""
    a, b = candidate.strip(), option.strip()
    if a.lower() == b.lower():
        return True
    if _is_integer_label(a) and _is_integer_label(b):
        return int(a, 10) == int(b, 10) and a == b
    try:
        return Decimal(a) == Decimal(b)
    except (InvalidOperation, ValueError):
        return False


def canonical_enum_option(text: str, options: List[str]) -> Optional[str]:
    """Resolve LLM/user text to a single configured option, or None if ambiguous."""
    needle = text.strip()
    if not needle or not options:
        return None
    needle_lower = needle.lower()
    for opt in options:
        if opt.strip().lower() == needle_lower:
            return opt
    numeric_hits = [opt for opt in options if _numeric_option_same(needle, opt)]
    if len(numeric_hits) == 1:
        return numeric_hits[0]
    return None


def enum_numeric_matches_ambiguous(text: str, options: List[str]) -> bool:
    """True when more than one option could match numerically (skip loose fallbacks)."""
    needle = text.strip()
    if not needle:
        return False
    hits = [opt for opt in options if _numeric_option_same(needle, opt)]
    return len(hits) > 1


def _dedupe_labels(labels: List[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for label in labels:
        key = label.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(label)
    return out


def enum_option_labels_from_config(custom_config: Any) -> List[str]:
    if not isinstance(custom_config, dict):
        return []
    raw = custom_config.get("options")
    if not isinstance(raw, list):
        return []
    labels: List[str] = []
    for opt in raw:
        label = coerce_metric_option_label(opt)
        if label is not None:
            labels.append(label)
    return _dedupe_labels(labels)


def classification_choice_labels_from_config(custom_config: Any) -> List[str]:
    normalized = _normalize_classification_choice_criteria(
        _classification_choice_criteria_raw(custom_config)
    )
    return list(normalized.keys()) if normalized else []


def _classification_choice_criteria_raw(custom_config: Any) -> Any:
    if not isinstance(custom_config, dict):
        return None
    choice = custom_config.get("choice")
    if not isinstance(choice, dict):
        return None
    return choice.get("criteria")


def _normalize_classification_choice_criteria(criteria: Any) -> Optional[Dict[str, str]]:
    if isinstance(criteria, dict):
        out: Dict[str, str] = {}
        for raw_key, raw_desc in criteria.items():
            key = coerce_metric_option_label(raw_key) or _scalar_option_to_string(raw_key)
            if not key or key in out:
                continue
            desc = raw_desc if isinstance(raw_desc, str) else str(raw_desc or "")
            out[key] = desc.strip() or key
        return out
    if isinstance(criteria, list):
        out: Dict[str, str] = {}
        for item in criteria:
            if not isinstance(item, dict):
                label = coerce_metric_option_label(item)
                if label and label not in out:
                    out[label] = label
                continue
            key = coerce_metric_option_label(item)
            if not key or key in out:
                continue
            desc = item.get("description") or item.get("desc") or key
            out[key] = str(desc).strip() or key
        return out if out else None
    return None


def classification_score_labels_from_config(custom_config: Any) -> List[str]:
    if not isinstance(custom_config, dict):
        return []
    score = custom_config.get("score")
    if not isinstance(score, dict):
        return []
    criteria = score.get("criteria")
    if not isinstance(criteria, list):
        return []
    labels: List[str] = []
    for level in criteria:
        label = coerce_metric_option_label(level)
        if label is not None:
            labels.append(label)
    return _dedupe_labels(labels)


def _normalize_classification_config(custom_config: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    updated = dict(custom_config)
    changed = False

    choice = updated.get("choice")
    if isinstance(choice, dict):
        raw_criteria = choice.get("criteria")
        normalized_choice = _normalize_classification_choice_criteria(raw_criteria)
        if normalized_choice is not None and normalized_choice != raw_criteria:
            updated["choice"] = {**choice, "criteria": normalized_choice}
            changed = True

    score = updated.get("score")
    if isinstance(score, dict) and isinstance(score.get("criteria"), list):
        normalized_levels = classification_score_labels_from_config(updated)
        if normalized_levels != score.get("criteria"):
            updated["score"] = {**score, "criteria": normalized_levels}
            changed = True

    return updated, changed


def custom_config_for_api(custom_data_type: Optional[str], custom_config: Any) -> Any:
    if not isinstance(custom_config, dict):
        return custom_config
    updated = dict(custom_config)
    changed = False
    dtype = (custom_data_type or "").strip().lower()

    if dtype == "enum":
        options = updated.get("options")
        if isinstance(options, list):
            normalized = enum_option_labels_from_config(updated)
            if normalized != options:
                updated["options"] = normalized
                changed = True

    if dtype == "classification":
        updated, cls_changed = _normalize_classification_config(updated)
        changed = changed or cls_changed

    return updated if changed else custom_config


def coerce_custom_config_for_storage(
    custom_data_type: Optional[str], custom_config: Any
) -> Any:
    """Persist canonical option labels (same rules as API responses)."""
    return custom_config_for_api(custom_data_type, custom_config)
