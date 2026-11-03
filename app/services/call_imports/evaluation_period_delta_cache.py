"""Persist week-over-week failure-rate deltas without recomputing on every GET."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.database import CallImportEvaluation

_MAX_CACHED_PERIOD_DELTA_KEYS = 8


def failure_policy_cache_version(metric_clusters: Any) -> str:
    """Token for the failure rules a cached comparison was computed with.

    Inferred rules (nothing stored) share one token. Saved policies include
    their content, so a later policy edit misses the previous cache entry.
    """
    if not isinstance(metric_clusters, dict):
        return "inferred"
    policies = metric_clusters.get("failure_policies")
    if not isinstance(policies, dict) or not policies:
        return "inferred"
    payload = {
        "source": metric_clusters.get("failure_policies_source") or "inferred",
        "updated_at": metric_clusters.get("failure_policies_updated_at") or "",
        "policies": policies,
    }
    blob = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def period_delta_numeric_cache_key(
    baseline_evaluation_id: UUID,
    *,
    completed_rows: int,
    baseline_completed_rows: int,
    metric_clusters: Any = None,
    policy_version: str | None = None,
) -> str:
    version = (
        policy_version
        if policy_version is not None
        else failure_policy_cache_version(metric_clusters)
    )
    return (
        f"{baseline_evaluation_id}:{completed_rows}:"
        f"{baseline_completed_rows}:{version}:reconciled-v2"
    )


def load_cached_period_deltas(
    evaluation: CallImportEvaluation,
    cache_key: str,
) -> Optional[dict[str, dict[str, str]]]:
    raw = getattr(evaluation, "cached_period_deltas", None)
    if not isinstance(raw, dict):
        return None
    entry = raw.get(cache_key)
    if not isinstance(entry, dict):
        return None
    deltas = entry.get("deltas")
    if not isinstance(deltas, dict):
        return None
    return {
        str(metric_id): dict(delta)
        for metric_id, delta in deltas.items()
        if isinstance(delta, dict)
    }


def save_cached_period_deltas(
    db: Session,
    evaluation: CallImportEvaluation,
    cache_key: str,
    deltas: dict[str, dict[str, str]],
) -> None:
    raw = evaluation.cached_period_deltas
    if not isinstance(raw, dict):
        raw = {}
    updated: Dict[str, Any] = dict(raw)
    updated[cache_key] = {"deltas": deltas}
    if len(updated) > _MAX_CACHED_PERIOD_DELTA_KEYS:
        for stale_key in list(updated.keys())[:-_MAX_CACHED_PERIOD_DELTA_KEYS]:
            if stale_key != cache_key:
                updated.pop(stale_key, None)
    evaluation.cached_period_deltas = updated
    flag_modified(evaluation, "cached_period_deltas")
    db.flush()
