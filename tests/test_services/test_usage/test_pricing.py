"""Tests for usage pricing computation and rate resolution."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4

from app.services.usage.pricing import (
    CostBreakdown,
    RateCard,
    UsageMetrics,
    _catalog_lookup_models,
    _normalize_pricing_block,
    _normalize_rate_source,
    compute_cost,
    RATE_SOURCE_CATALOG,
)


def test_compute_cost_llm_token_breakdown():
    rate = RateCard(
        source=RATE_SOURCE_CATALOG,
        rate_id=uuid4(),
        input_micro_usd_per_million=1_000_000,
        output_micro_usd_per_million=2_000_000,
        cache_read_micro_usd_per_million=500_000,
        cache_creation_micro_usd_per_million=1_250_000,
    )
    costs = compute_cost(
        UsageMetrics(
            prompt_tokens=1_000_000,
            completion_tokens=500_000,
            cache_read_tokens=200_000,
            cache_creation_tokens=100_000,
        ),
        rate,
    )
    assert costs.input_cost_micro_usd == 1_000_000
    assert costs.output_cost_micro_usd == 1_000_000
    assert costs.cache_read_cost_micro_usd == 100_000
    assert costs.cache_creation_cost_micro_usd == 125_000
    assert costs.total_cost_micro_usd == 2_225_000
    assert costs.pricing_rate_source == RATE_SOURCE_CATALOG


def test_compute_cost_stt_audio_seconds():
    rate = RateCard(
        source=RATE_SOURCE_CATALOG,
        rate_id=uuid4(),
        audio_micro_usd_per_second=100,
    )
    costs = compute_cost(UsageMetrics(audio_seconds=90), rate)
    assert costs.audio_cost_micro_usd == 9_000
    assert costs.total_cost_micro_usd == 9_000


def test_compute_cost_tts_characters():
    rate = RateCard(
        source=RATE_SOURCE_CATALOG,
        rate_id=uuid4(),
        tts_micro_usd_per_million_chars=15_000_000,
    )
    costs = compute_cost(UsageMetrics(tts_characters=2_000_000), rate)
    assert costs.tts_cost_micro_usd == 30_000_000
    assert costs.total_cost_micro_usd == 30_000_000


def test_compute_cost_without_rate_is_zero():
    costs = compute_cost(UsageMetrics(prompt_tokens=10_000), None)
    assert costs == CostBreakdown()


def test_normalize_rate_source_truncates_long_values():
    long_source = "x" * 300
    assert len(_normalize_rate_source(long_source)) == 255


def test_normalize_pricing_block_plan_format():
    normalized = _normalize_pricing_block(
        {
            "input_per_1m": 2.5,
            "output_per_1m": 10.0,
            "cache_read_per_1m": 1.25,
            "cache_write_per_1m": 0.0,
            "source": "litellm_import",
        },
        model_type="llm",
    )
    assert normalized["usage_kind"] == "llm"
    assert normalized["input_micro_usd_per_million"] == 2_500_000
    assert normalized["output_micro_usd_per_million"] == 10_000_000
    assert normalized["cache_read_micro_usd_per_million"] == 1_250_000
    assert normalized["source"] == "litellm_import"


def test_normalize_pricing_block_stt_audio_per_minute():
    normalized = _normalize_pricing_block(
        {"audio_per_minute": 0.36, "usage_kind": "stt"},
        model_type="stt",
    )
    assert normalized["usage_kind"] == "stt"
    assert normalized["audio_micro_usd_per_second"] == 6_000


def test_catalog_lookup_models_includes_azure_alias():
    assert _catalog_lookup_models("gpt-4o", "llm") == ("gpt-4o", "azure-gpt-4o")
    assert _catalog_lookup_models("azure-gpt-4o", "llm") == (
        "azure-gpt-4o",
        "gpt-4o",
    )


def test_compute_cost_reasoning_tokens():
    rate = RateCard(
        source=RATE_SOURCE_CATALOG,
        rate_id=uuid4(),
        reasoning_micro_usd_per_million=3_000_000,
    )
    costs = compute_cost(UsageMetrics(reasoning_tokens=1_000_000), rate)
    assert costs.reasoning_cost_micro_usd == 3_000_000
    assert costs.total_cost_micro_usd == 3_000_000


def test_cost_fields_from_deltas_voice_agent_call_audio():
    from app.services.usage.pricing import (
        RateCard,
        _pricing_entries_from_models_json,
        cost_fields_from_deltas,
    )

    entries = _pricing_entries_from_models_json()
    assert "voice-agent-call" in entries
    assert "unknown" in entries
    assert entries["voice-agent-call"]["audio_micro_usd_per_second"] > 0

    rate = RateCard(
        source="catalog",
        rate_id=uuid4(),
        audio_micro_usd_per_second=833,  # ~$0.05/min
    )
    fields = cost_fields_from_deltas(
        {"audio_seconds": 60, "call_count": 1},
        organization_id=uuid4(),
        model="voice-agent-call",
        usage_kind="llm",
        usage_date=date(2026, 8, 11),
        db=MagicMock(),
        resolver=MagicMock(resolve_rate=MagicMock(return_value=rate)),
    )
    assert fields["audio_cost_micro_usd"] == 60 * 833
    assert fields["total_cost_micro_usd"] == fields["audio_cost_micro_usd"]
    assert fields["pricing_rate_source"] == "catalog"


def test_resolve_rate_ignores_stale_negative_cache(monkeypatch):
    from unittest.mock import MagicMock

    import app.services.usage.pricing as pricing_mod
    import app.services.usage.pricing_cache as pricing_cache_mod
    from app.services.usage.pricing import RATE_SOURCE_CATALOG, PricingResolver
    from tests.test_services.test_usage.test_pricing_cache import _FakeRedis

    pricing_mod._RATES_TABLE_CACHE = "model_pricing_rates"

    org_id = uuid4()
    rate_id = uuid4()
    usage_day = date(2026, 8, 11)

    fake_redis = _FakeRedis()
    monkeypatch.setattr(pricing_cache_mod, "_client", lambda: fake_redis)

    redis_key = pricing_cache_mod.pricing_cache_key(
        organization_id=org_id,
        model="gpt-oss-120b",
        usage_kind="llm",
        usage_date=usage_day,
    )
    pricing_cache_mod.set_cached_rate_payload(redis_key, None)

    row = {
        "id": rate_id,
        "input_micro_usd_per_million": 1_000_000,
        "output_micro_usd_per_million": 2_000_000,
        "cache_read_micro_usd_per_million": 0,
        "cache_creation_micro_usd_per_million": 0,
        "reasoning_micro_usd_per_million": 0,
        "audio_micro_usd_per_second": 0,
        "tts_micro_usd_per_million_chars": 0,
    }

    override_result = MagicMock()
    override_result.mappings.return_value.first.return_value = None
    catalog_result = MagicMock()
    catalog_result.mappings.return_value.first.return_value = row

    db = MagicMock()
    db.execute.side_effect = [override_result, catalog_result]

    resolver = PricingResolver(db)
    card = resolver.resolve_rate(
        organization_id=org_id,
        model="gpt-oss-120b",
        usage_kind="llm",
        usage_date=usage_day,
    )

    assert card is not None
    assert card.rate_id == rate_id
    assert card.source == RATE_SOURCE_CATALOG
    assert fake_redis.store[redis_key] != "__null__"
