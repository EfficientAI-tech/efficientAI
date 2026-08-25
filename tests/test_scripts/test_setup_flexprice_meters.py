from scripts.setup_flexprice_meters import meter_aggregation_matches
from app.api.v1.routes.call_import_evaluations import (
    DISCOVERED_METRICS_KEY,
    _is_metric_scores_meta_key,
)


def test_meter_aggregation_matches_sum_quantity():
    meter = {"aggregation": {"type": "SUM", "field": "quantity"}}
    assert meter_aggregation_matches(meter, agg_type="SUM", agg_field="quantity") is True


def test_meter_aggregation_matches_rejects_count():
    meter = {"aggregation": {"type": "COUNT"}}
    assert meter_aggregation_matches(meter, agg_type="SUM", agg_field="quantity") is False


def test_metric_scores_meta_keys():
    assert _is_metric_scores_meta_key("_billing") is True
    assert _is_metric_scores_meta_key(DISCOVERED_METRICS_KEY) is True
    assert _is_metric_scores_meta_key("parent-id__discovered") is True
    assert _is_metric_scores_meta_key("550e8400-e29b-41d4-a716-446655440000") is False
