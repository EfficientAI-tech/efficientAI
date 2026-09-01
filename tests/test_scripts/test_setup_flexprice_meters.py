import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parents[2]
SETUP_SCRIPT = REPO_ROOT / "scripts" / "setup_flexprice_meters.py"


def _load_setup_flexprice_meters():
    spec = importlib.util.spec_from_file_location(
        "setup_flexprice_meters",
        SETUP_SCRIPT,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_setup_flexprice_meters = _load_setup_flexprice_meters()
AGENT_PLAYGROUND_PRIMARY_EVENT = _setup_flexprice_meters.AGENT_PLAYGROUND_PRIMARY_EVENT
EVALUATOR_RUN_COMPLETED_EVENT = _setup_flexprice_meters.EVALUATOR_RUN_COMPLETED_EVENT
GEPA_PRIMARY_EVENT = _setup_flexprice_meters.GEPA_PRIMARY_EVENT
JUDGE_ALIGNMENT_PRIMARY_EVENT = _setup_flexprice_meters.JUDGE_ALIGNMENT_PRIMARY_EVENT
LICENSE_FEATURES = _setup_flexprice_meters.LICENSE_FEATURES
METRICS_AI_ASSIST_EVENT = _setup_flexprice_meters.METRICS_AI_ASSIST_EVENT
METRIC_STUDIO_PRIMARY_EVENT = _setup_flexprice_meters.METRIC_STUDIO_PRIMARY_EVENT
PLAN_BILLABLE_METERS = _setup_flexprice_meters.PLAN_BILLABLE_METERS
PROMPT_PARTIAL_AI_ASSISTED_EVENT = _setup_flexprice_meters.PROMPT_PARTIAL_AI_ASSISTED_EVENT
SCENARIO_AI_TEXT_EVENT = _setup_flexprice_meters.SCENARIO_AI_TEXT_EVENT
VOICE_PLAYGROUND_PRIMARY_EVENT = _setup_flexprice_meters.VOICE_PLAYGROUND_PRIMARY_EVENT
_feature_meter_is_canonical = _setup_flexprice_meters._feature_meter_is_canonical
_pick_canonical_meter = _setup_flexprice_meters._pick_canonical_meter
meter_aggregation_matches = _setup_flexprice_meters.meter_aggregation_matches
repair_license_features = _setup_flexprice_meters.repair_license_features
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
        "call_import.user_insights_generated",
        "call_import.prompt_improvements_generated",
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


def test_prompt_partials_license_feature_spec():
    spec = next(item for item in LICENSE_FEATURES if item["lookup_key"] == "prompt_partials")
    assert spec["event_name"] == PROMPT_PARTIAL_AI_ASSISTED_EVENT
    assert spec["aggregation"] == {"type": "COUNT"}


def test_metric_scores_meta_keys():
    assert _is_metric_scores_meta_key("_billing") is True
    assert _is_metric_scores_meta_key(DISCOVERED_METRICS_KEY) is True
    assert _is_metric_scores_meta_key("parent-id__discovered") is True
    assert _is_metric_scores_meta_key("550e8400-e29b-41d4-a716-446655440000") is False


def test_pick_canonical_meter_prefers_priced_meter():
    meters = [
        {"id": "m-old", "aggregation": {"type": "SUM", "field": "quantity"}, "status": "published"},
        {"id": "m-new", "aggregation": {"type": "SUM", "field": "quantity"}, "status": "published"},
    ]
    prices = [{"meter_id": "m-new", "amount": "0", "status": "published"}]
    picked = _pick_canonical_meter(meters, prices, agg_type="SUM", agg_field="quantity")
    assert picked["id"] == "m-new"


def test_feature_meter_is_canonical():
    feature = {"meter_id": "m1"}
    meter = {
        "id": "m1",
        "status": "published",
        "aggregation": {"type": "SUM", "field": "quantity"},
    }
    assert _feature_meter_is_canonical(
        feature,
        meter,
        canonical_meter_id="m1",
        agg_type="SUM",
        agg_field="quantity",
    )


def test_repair_license_features_dry_run_flags_stale_call_imports():
    client = MagicMock()
    sdk = MagicMock()
    client.get.side_effect = [
        MagicMock(
            status_code=200,
            json=lambda: {
                "items": [
                    {
                        "id": "meter_old",
                        "event_name": "call_import.batch_created",
                        "aggregation": {"type": "COUNT"},
                        "status": "archived",
                    },
                    {
                        "id": "meter_new",
                        "event_name": "call_import.batch_created",
                        "aggregation": {"type": "SUM", "field": "quantity"},
                        "status": "published",
                    },
                ],
                "pagination": {"total": 2},
            },
        ),
        MagicMock(status_code=200, json=lambda: {"items": [], "pagination": {"total": 0}}),
        MagicMock(
            status_code=200,
            json=lambda: {
                "items": [
                    {
                        "id": "feat_1",
                        "lookup_key": "call_imports",
                        "meter_id": "meter_old",
                    }
                ],
                "pagination": {"total": 1},
            },
        ),
    ]
    client.get.return_value.raise_for_status = MagicMock()

    result = repair_license_features(client, sdk, dry_run=True)
    repaired_keys = {row["lookup_key"] for row in result["repaired"]}
    assert "call_imports" in repaired_keys
    sdk.features.delete_feature.assert_not_called()
