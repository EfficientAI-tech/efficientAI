"""Validate JSON content for metric-definition prompt partials."""

from __future__ import annotations

import json
from typing import Any, Optional, Sequence

from app.services.metric_partial_constants import METRIC_PARTIAL_TAG


def _partial_has_metric_tag(tags: Optional[Sequence[str]]) -> bool:
    if not tags:
        return False
    return METRIC_PARTIAL_TAG in [str(tag) for tag in tags]


def validate_metric_partial_content(
    content: str,
    tags: Optional[Sequence[str]] = None,
) -> None:
    """Raise ValueError when metric-tagged partial content is invalid."""
    if not _partial_has_metric_tag(tags):
        return

    text = (content or "").strip()
    if not text:
        raise ValueError("Metric partial content cannot be empty")

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("Metric partial content must be valid JSON") from exc

    if not isinstance(parsed, dict):
        raise ValueError("Metric partial JSON must be an object")

    schema_version = parsed.get("schema_version")
    if schema_version != 1:
        raise ValueError("Metric partial JSON must include schema_version: 1")

    metric_kind = str(parsed.get("metric_kind") or "").strip().lower()
    if metric_kind not in {"single", "category"}:
        raise ValueError("Metric partial JSON must set metric_kind to single or category")

    description = str(parsed.get("description") or "").strip()
    if not description:
        raise ValueError("Metric partial JSON must include a non-empty description")

    if metric_kind == "category":
        children = parsed.get("children")
        if not isinstance(children, list) or not children:
            raise ValueError("Category metric partials must include a non-empty children array")
        for child in children:
            if not isinstance(child, dict):
                raise ValueError("Each category child must be an object")
            if not str(child.get("name") or "").strip():
                raise ValueError("Each category child must include a name")
            if not str(child.get("description") or "").strip():
                raise ValueError("Each category child must include a description")
