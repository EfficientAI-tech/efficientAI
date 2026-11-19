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


def test_result_matches_usage_row_scope_limits_to_usage_day():
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from app.services.evaluators.evaluator_result_usage_enrichment import _result_matches_usage_row_scope

    usage_day = datetime(2025, 10, 21, tzinfo=timezone.utc).date()
    row = SimpleNamespace(
        usage_date=usage_day,
        context={"agent_id": "00000000-0000-0000-0000-000000000001"},
    )
    on_day = SimpleNamespace(
        agent_id=__import__("uuid").UUID("00000000-0000-0000-0000-000000000001"),
        scenario_id=None,
        evaluator_id=None,
        timestamp=datetime(2025, 10, 21, 12, 0, tzinfo=timezone.utc),
    )
    next_day = SimpleNamespace(
        agent_id=__import__("uuid").UUID("00000000-0000-0000-0000-000000000001"),
        scenario_id=None,
        evaluator_id=None,
        timestamp=datetime(2025, 10, 22, 12, 0, tzinfo=timezone.utc),
    )
    since = datetime(2025, 10, 1, tzinfo=timezone.utc)
    until = datetime(2025, 10, 31, tzinfo=timezone.utc)
    assert _result_matches_usage_row_scope(on_day, row=row, since=since, until=until)
    assert not _result_matches_usage_row_scope(next_day, row=row, since=since, until=until)


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