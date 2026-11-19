from app.services.evaluators.evaluator_result_usage_enrichment import (
    enrich_call_data_for_usage_display,
    merge_call_data_usage_fields,
)


def test_merge_call_data_usage_fields_fills_missing_cost_breakdown():
    base = {"source": "playground"}
    overlay = {"cost_breakdown": {"llm": 0.02, "total": 0.05}, "llm_token_usage": {"total_tokens": 1200}}
    merged = merge_call_data_usage_fields(base, overlay)
    assert merged["cost_breakdown"]["total"] == 0.05
    assert merged["llm_token_usage"]["total_tokens"] == 1200
    assert merged["source"] == "playground"


def test_enrich_call_data_applies_daily_rollup_when_provider_fields_missing():
    out = enrich_call_data_for_usage_display(
        {},
        recording_call_data=None,
        rollup=(1500, 89_900),
        rollup_by_model={"gpt-5-nano": (1500, 89_900)},
    )
    assert out["usage"]["total_tokens"] == 1500
    assert out["usage"]["total_cost_usd"] == 0.0899
    assert out["usage_by_model"]["gpt-5-nano"]["total_cost_usd"] == 0.0899