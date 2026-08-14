"""Tests for usage cost presentation helpers."""

from app.services.usage.usage_costs import costs_from_micro, micro_to_usd


def test_micro_to_usd():
    assert micro_to_usd(1_500_000) == 1.5
    assert micro_to_usd(0) == 0


def test_costs_from_micro_maps_cache_write_and_unpriced_flag():
    costs = costs_from_micro(
        input_cost_micro_usd=1_000_000,
        output_cost_micro_usd=500_000,
        cache_creation_cost_micro_usd=250_000,
        total_cost_micro_usd=1_750_000,
        has_unpriced_usage=True,
    )
    assert costs["input_cost_usd"] == 1.0
    assert costs["output_cost_usd"] == 0.5
    assert costs["cache_write_cost_usd"] == 0.25
    assert costs["total_cost_usd"] == 1.75
    assert costs["currency"] == "USD"
    assert costs["has_unpriced_usage"] is True


def test_costs_from_micro_sums_total_when_not_provided():
    costs = costs_from_micro(
        input_cost_micro_usd=100,
        output_cost_micro_usd=200,
        audio_cost_micro_usd=300,
    )
    assert costs["total_cost_usd"] == micro_to_usd(600)
