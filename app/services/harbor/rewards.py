"""Normalize platform metric scores into Harbor rewards in [0, 1]."""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional

AGGREGATE_REWARD_KEY = "reward"


def metric_reward_key(name: str, taken: set[str]) -> str:
    """Stable, unique snake_case key for a metric name inside one rewards dict."""
    base = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_") or "metric"
    if base == AGGREGATE_REWARD_KEY:
        base = f"metric_{base}"
    key = base
    suffix = 2
    while key in taken:
        key = f"{base}_{suffix}"
        suffix += 1
    taken.add(key)
    return key


def _metric_type(entry: dict[str, Any], metric: Any) -> str:
    raw = entry.get("type") or getattr(metric, "metric_type", None) or ""
    if hasattr(raw, "value"):
        raw = raw.value
    return str(raw).lower()


def normalize_metric_score(entry: Optional[dict[str, Any]], metric: Any) -> Optional[float]:
    """Map one ``metric_scores`` entry to [0, 1]; ``None`` when it shouldn't count.

    Rating values are already 0–1 (see ``score_utils.normalize_score``). Booleans map
    to 1/0. Numbers need a ``custom_config`` min/max range. Categorization child
    labels, text, enum and errored/skipped scores don't contribute.
    """
    if not isinstance(entry, dict) or getattr(metric, "parent_metric_id", None):
        return None
    if entry.get("error") or entry.get("skipped"):
        return None
    value = entry.get("value")
    if value is None:
        return None

    metric_type = _metric_type(entry, metric)
    if metric_type == "rating":
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return None
    if metric_type == "boolean":
        if isinstance(value, str):
            return 1.0 if value.strip().lower() in ("true", "yes", "1") else 0.0
        return 1.0 if bool(value) else 0.0
    if metric_type == "number":
        cfg = getattr(metric, "custom_config", None) or {}
        lo, hi = cfg.get("min"), cfg.get("max")
        try:
            lo, hi, v = float(lo), float(hi), float(value)
        except (TypeError, ValueError):
            return None
        if hi <= lo:
            return None
        return max(0.0, min(1.0, (v - lo) / (hi - lo)))
    return None


def compute_rewards(
    metric_scores: dict[str, Any],
    metrics: Iterable[Any],
) -> tuple[Optional[float], dict[str, float], dict[str, str]]:
    """Return ``(aggregate, rewards_by_key, metric_id_by_key)``.

    The aggregate is the unweighted mean of every scorable metric, or ``None``
    when nothing was scorable.
    """
    rewards: dict[str, float] = {}
    metric_ids: dict[str, str] = {}
    taken: set[str] = {AGGREGATE_REWARD_KEY}
    for metric in metrics:
        score = normalize_metric_score(metric_scores.get(str(metric.id)), metric)
        if score is None:
            continue
        key = metric_reward_key(metric.name, taken)
        rewards[key] = round(score, 4)
        metric_ids[key] = str(metric.id)
    aggregate = round(sum(rewards.values()) / len(rewards), 4) if rewards else None
    return aggregate, rewards, metric_ids
