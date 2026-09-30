"""Validate Jev classification metric ``custom_config`` payloads."""

from __future__ import annotations

from typing import Any, Dict, Optional

CLASSIFICATION_CUSTOM_DATA_TYPE = "classification"

_QUESTION_KEYS = ("noul", "choice", "score")


def is_classification_metric(
    *,
    custom_data_type: Optional[str],
) -> bool:
    return (custom_data_type or "").strip().lower() == CLASSIFICATION_CUSTOM_DATA_TYPE


def validate_classification_custom_config(
    custom_config: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Return normalized config or raise ValueError."""
    if not isinstance(custom_config, dict):
        raise ValueError(
            "Classification metrics require custom_config to be a JSON object "
            "with noul, choice, and/or score question definitions."
        )

    enabled_count = 0
    normalized: Dict[str, Any] = {}

    for key in _QUESTION_KEYS:
        block = custom_config.get(key)
        if block is None:
            normalized[key] = {"enabled": False}
            continue
        if not isinstance(block, dict):
            raise ValueError(f"Classification '{key}' must be an object.")
        enabled = bool(block.get("enabled"))
        instructions = str(block.get("instructions") or "").strip()
        entry: Dict[str, Any] = {"enabled": enabled}
        if enabled:
            enabled_count += 1
            if not instructions:
                raise ValueError(
                    f"Classification '{key}' requires non-empty instructions when enabled."
                )
            entry["instructions"] = instructions

            if key == "noul":
                criteria = block.get("criteria")
                if not isinstance(criteria, dict):
                    raise ValueError(
                        "Classification noul requires criteria with true and false descriptions."
                    )
                true_desc = str(criteria.get("true") or "").strip()
                false_desc = str(criteria.get("false") or "").strip()
                if not true_desc or not false_desc:
                    raise ValueError(
                        "Classification noul requires non-empty criteria for both "
                        "'true' and 'false'."
                    )
                entry["criteria"] = {"true": true_desc, "false": false_desc}

            elif key == "choice":
                criteria = block.get("criteria")
                if not isinstance(criteria, dict) or len(criteria) < 2:
                    raise ValueError(
                        "Classification choice requires at least two option labels "
                        "with descriptions in criteria."
                    )
                choice_criteria: Dict[str, str] = {}
                for label, desc in criteria.items():
                    label_str = str(label or "").strip()
                    desc_str = str(desc or "").strip()
                    if not label_str:
                        raise ValueError("Classification choice options need non-empty labels.")
                    if not desc_str:
                        raise ValueError(
                            f"Classification choice option '{label_str}' needs a description."
                        )
                    choice_criteria[label_str] = desc_str
                entry["criteria"] = choice_criteria

            elif key == "score":
                criteria = block.get("criteria")
                if not isinstance(criteria, list) or len(criteria) < 2:
                    raise ValueError(
                        "Classification score requires an ordered list of at least "
                        "two level labels in criteria."
                    )
                levels: list[str] = []
                for level in criteria:
                    level_str = str(level or "").strip()
                    if not level_str:
                        raise ValueError("Classification score levels cannot be empty.")
                    levels.append(level_str)
                entry["criteria"] = levels
        else:
            if block.get("instructions"):
                entry["instructions"] = str(block.get("instructions") or "").strip()
            if key == "noul" and isinstance(block.get("criteria"), dict):
                entry["criteria"] = block.get("criteria")
            if key == "choice" and isinstance(block.get("criteria"), dict):
                entry["criteria"] = block.get("criteria")
            if key == "score" and isinstance(block.get("criteria"), list):
                entry["criteria"] = block.get("criteria")

        normalized[key] = entry

    if enabled_count == 0:
        raise ValueError(
            "Classification metrics must enable at least one of noul, choice, or score."
        )

    return normalized


def assert_classification_metric_shape(
    *,
    custom_data_type: Optional[str],
    custom_config: Optional[Dict[str, Any]],
    metric_type: Optional[str] = None,
    parent_metric_id: Any = None,
    selection_mode: Any = None,
    compare_transcripts: bool = False,
) -> Optional[Dict[str, Any]]:
    """Validate classification metric fields; return normalized config when applicable."""
    if not is_classification_metric(custom_data_type=custom_data_type):
        return None

    if parent_metric_id is not None:
        raise ValueError(
            "Classification metrics must be standalone (no parent_metric_id)."
        )
    if selection_mode is not None:
        raise ValueError(
            "Classification metrics must be standalone (selection_mode must be unset)."
        )
    if compare_transcripts:
        raise ValueError(
            "Classification metrics cannot use compare_transcripts."
        )
    if metric_type is not None:
        m = (
            metric_type.value
            if hasattr(metric_type, "value")
            else str(metric_type)
        ).lower()
        if m != "text":
            raise ValueError("Classification metrics must use metric_type 'text'.")

    return validate_classification_custom_config(custom_config)
