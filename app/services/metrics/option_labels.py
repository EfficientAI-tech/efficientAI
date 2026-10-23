"""Normalize metric enum / classification option shapes from DB or LLM."""

from typing import Any, List, Optional


def coerce_metric_option_label(opt: Any) -> Optional[str]:
    if isinstance(opt, str):
        stripped = opt.strip()
        return stripped or None
    if isinstance(opt, dict):
        for key in ("value", "label", "name", "description"):
            val = opt.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return None


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
        elif isinstance(opt, str) and opt.strip():
            labels.append(opt.strip())
    return labels


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
        elif isinstance(level, str) and level.strip():
            labels.append(level.strip())
        elif level is not None:
            labels.append(str(level))
    return labels


def custom_config_for_api(custom_data_type: Optional[str], custom_config: Any) -> Any:
    if not isinstance(custom_config, dict):
        return custom_config
    updated = dict(custom_config)
    changed = False

    if custom_data_type == "enum":
        options = updated.get("options")
        if isinstance(options, list):
            normalized = enum_option_labels_from_config(updated)
            if normalized and normalized != options:
                updated["options"] = normalized
                changed = True

    if custom_data_type == "classification":
        score = updated.get("score")
        if isinstance(score, dict) and isinstance(score.get("criteria"), list):
            normalized_levels = classification_score_labels_from_config(updated)
            if normalized_levels and normalized_levels != score.get("criteria"):
                updated["score"] = {**score, "criteria": normalized_levels}
                changed = True

    return updated if changed else custom_config
