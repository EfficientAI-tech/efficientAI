from unittest.mock import MagicMock
from uuid import uuid4

from app.services.call_imports.evaluation_period_delta_cache import (
    failure_policy_cache_version,
    load_cached_period_deltas,
    period_delta_numeric_cache_key,
    save_cached_period_deltas,
)


def test_period_delta_cache_key_matches_explanation_watermark():
    baseline_id = uuid4()
    key = period_delta_numeric_cache_key(
        baseline_id,
        completed_rows=100,
        baseline_completed_rows=90,
    )
    assert key.endswith(":inferred:reconciled-v2")
    assert str(baseline_id) in key


def test_period_delta_cache_key_changes_when_failure_policies_change():
    baseline_id = uuid4()
    old_clusters = {
        "failure_policies_source": "user",
        "failure_policies_updated_at": "2026-10-01T00:00:00+00:00",
        "failure_policies": {"m1": {"failure_values": ["no"]}},
    }
    new_clusters = {
        "failure_policies_source": "user",
        "failure_policies_updated_at": "2026-11-01T00:00:00+00:00",
        "failure_policies": {"m1": {"failure_values": ["yes"]}},
    }
    old_key = period_delta_numeric_cache_key(
        baseline_id,
        completed_rows=10,
        baseline_completed_rows=10,
        metric_clusters=old_clusters,
    )
    new_key = period_delta_numeric_cache_key(
        baseline_id,
        completed_rows=10,
        baseline_completed_rows=10,
        metric_clusters=new_clusters,
    )
    assert old_key != new_key
    assert failure_policy_cache_version(old_clusters) in old_key
    assert failure_policy_cache_version({}) == "inferred"


def test_save_and_load_period_deltas_roundtrip(monkeypatch):
    class Eval:
        cached_period_deltas = None

    evaluation = Eval()
    db = MagicMock()
    monkeypatch.setattr(
        "app.services.call_imports.evaluation_period_delta_cache.flag_modified",
        lambda *_args, **_kwargs: None,
    )
    key = "baseline:10:9:reconciled-v2"
    deltas = {"metric-1": {"label": "+1.0 pp", "detail": "x vs y"}}
    save_cached_period_deltas(db, evaluation, key, deltas)  # type: ignore[arg-type]
    loaded = load_cached_period_deltas(evaluation, key)
    assert loaded == deltas
    assert load_cached_period_deltas(evaluation, "other-key") is None
