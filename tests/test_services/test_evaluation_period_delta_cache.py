from unittest.mock import MagicMock
from uuid import uuid4

from app.services.call_imports.evaluation_period_delta_cache import (
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
    assert key.endswith(":reconciled-v2")
    assert str(baseline_id) in key


def test_save_and_load_period_deltas_roundtrip():
    class Eval:
        cached_period_deltas = None

    evaluation = Eval()
    db = MagicMock()
    key = "baseline:10:9:reconciled-v2"
    deltas = {"metric-1": {"label": "+1.0 pp", "detail": "x vs y"}}
    save_cached_period_deltas(db, evaluation, key, deltas)  # type: ignore[arg-type]
    loaded = load_cached_period_deltas(evaluation, key)
    assert loaded == deltas
    assert load_cached_period_deltas(evaluation, "other-key") is None
