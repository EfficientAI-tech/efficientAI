from scripts.setup_flexprice_meters import (
    AGENT_PLAYGROUND_PRIMARY_EVENT,
    EVALUATOR_RUN_COMPLETED_EVENT,
    GEPA_PRIMARY_EVENT,
    JUDGE_ALIGNMENT_PRIMARY_EVENT,
    LICENSE_FEATURES,
    METRICS_AI_ASSIST_EVENT,
    METRIC_STUDIO_PRIMARY_EVENT,
    PLAN_BILLABLE_METERS,
    SCENARIO_AI_TEXT_EVENT,
    VOICE_PLAYGROUND_PRIMARY_EVENT,
    meter_aggregation_matches,
)
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


def test_call_imports_plan_has_separate_paid_meters():
    call_import_lines = [row for row in PLAN_BILLABLE_METERS if row["product"] == "Call Imports"]
    paid_events = {row["event_name"] for row in call_import_lines if row.get("charge")}
    assert paid_events == {
        "call_import.evaluation_completed",
        "call_import.recording_minutes_billed",
        "call_import.pdf_report_generated",
    }


def test_agent_playground_license_feature_spec():
    spec = next(item for item in LICENSE_FEATURES if item["lookup_key"] == "agent_playground")
    assert spec["event_name"] == AGENT_PLAYGROUND_PRIMARY_EVENT
    assert spec["event_name"] == "playground.evaluation_completed"
    assert spec["aggregation"] == {"type": "SUM", "field": "billable_minutes"}


def test_voice_playground_license_feature_spec():
    spec = next(item for item in LICENSE_FEATURES if item["lookup_key"] == "voice_playground")
    assert spec["event_name"] == VOICE_PLAYGROUND_PRIMARY_EVENT
    assert spec["aggregation"] == {"type": "SUM", "field": "quantity"}


def test_evaluators_license_feature_spec():
    spec = next(item for item in LICENSE_FEATURES if item["lookup_key"] == "evaluators")
    assert spec["event_name"] == EVALUATOR_RUN_COMPLETED_EVENT
    assert spec["aggregation"] == {"type": "COUNT"}


def test_evaluators_plan_includes_audio_minutes_meter():
    evaluator_lines = [row for row in PLAN_BILLABLE_METERS if row["product"] == "Evaluators"]
    paid_events = {row["event_name"] for row in evaluator_lines if row.get("charge")}
    assert paid_events == {
        "evaluator.run_completed",
        "evaluator.recording_minutes_billed",
    }


def test_gepa_license_feature_spec():
    spec = next(item for item in LICENSE_FEATURES if item["lookup_key"] == "gepa_optimization")
    assert spec["event_name"] == GEPA_PRIMARY_EVENT
    assert spec["aggregation"] == {"type": "SUM", "field": "quantity"}


def test_judge_alignment_license_feature_spec():
    spec = next(item for item in LICENSE_FEATURES if item["lookup_key"] == "judge_alignment")
    assert spec["event_name"] == JUDGE_ALIGNMENT_PRIMARY_EVENT
    assert spec["aggregation"] == {"type": "SUM", "field": "quantity"}


def test_metrics_ai_assist_license_feature_spec():
    spec = next(item for item in LICENSE_FEATURES if item["lookup_key"] == "metrics_ai_assist")
    assert spec["event_name"] == METRICS_AI_ASSIST_EVENT
    assert spec["aggregation"] == {"type": "COUNT"}


def test_metric_studio_license_feature_spec():
    spec = next(item for item in LICENSE_FEATURES if item["lookup_key"] == "metric_studio")
    assert spec["event_name"] == METRIC_STUDIO_PRIMARY_EVENT
    assert spec["aggregation"] == {"type": "SUM", "field": "quantity"}


def test_scenario_ai_license_feature_spec():
    spec = next(item for item in LICENSE_FEATURES if item["lookup_key"] == "scenario_ai")
    assert spec["event_name"] == SCENARIO_AI_TEXT_EVENT
    assert spec["aggregation"] == {"type": "COUNT"}


def test_metric_scores_meta_keys():
    assert _is_metric_scores_meta_key("_billing") is True
    assert _is_metric_scores_meta_key(DISCOVERED_METRICS_KEY) is True
    assert _is_metric_scores_meta_key("parent-id__discovered") is True
    assert _is_metric_scores_meta_key("550e8400-e29b-41d4-a716-446655440000") is False
