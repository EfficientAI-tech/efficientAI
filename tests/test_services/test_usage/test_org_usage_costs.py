"""Tests for usage cost API response shaping."""

from types import SimpleNamespace

from app.api.v1.routes.org_usage import (
    _attach_costs,
    _breakdown_metrics_from_tuple,
    _usage_totals_from_row,
)


def test_usage_totals_from_row_includes_nested_costs():
    row = SimpleNamespace(
        prompt_tokens=100,
        completion_tokens=50,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        reasoning_tokens=0,
        audio_seconds=0,
        tts_characters=0,
        call_count=2,
        input_cost_micro_usd=1_000_000,
        output_cost_micro_usd=500_000,
        cache_read_cost_micro_usd=0,
        cache_creation_cost_micro_usd=0,
        reasoning_cost_micro_usd=0,
        audio_cost_micro_usd=0,
        tts_cost_micro_usd=0,
        total_cost_micro_usd=1_500_000,
        has_unpriced_usage=True,
    )
    totals = _usage_totals_from_row(row)
    assert totals["total_tokens"] == 150
    assert totals["costs"]["total_cost_usd"] == 1.5
    assert totals["costs"]["has_unpriced_usage"] is True


def test_breakdown_metrics_from_tuple_includes_costs():
    metrics = (
        10,
        5,
        0,
        0,
        0,
        0,
        0,
        1,
        100,
        50,
        0,
        0,
        0,
        0,
        0,
        150,
        True,
    )
    row = _breakdown_metrics_from_tuple(metrics)
    assert row["costs"]["total_cost_usd"] == 0.00015
    assert row["costs"]["has_unpriced_usage"] is True


def test_attach_costs_uses_cache_write_field_name():
    payload = _attach_costs(
        {
            "input_cost_micro_usd": 0,
            "output_cost_micro_usd": 0,
            "cache_read_cost_micro_usd": 0,
            "cache_creation_cost_micro_usd": 2_000_000,
            "reasoning_cost_micro_usd": 0,
            "audio_cost_micro_usd": 0,
            "tts_cost_micro_usd": 0,
            "total_cost_micro_usd": 2_000_000,
        }
    )
    assert payload["costs"]["cache_write_cost_usd"] == 2.0
