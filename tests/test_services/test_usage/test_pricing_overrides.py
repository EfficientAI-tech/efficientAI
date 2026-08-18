"""Tests for org pricing override merge and service helpers."""

from __future__ import annotations

from uuid import uuid4

from app.services.usage.pricing import (
    RATE_SOURCE_CATALOG,
    RATE_SOURCE_OVERRIDE,
    RateCard,
    _merge_override_with_catalog,
)
from app.services.usage.pricing_overrides import _usd_payload_to_micro_columns


def test_merge_override_inherits_null_fields_from_catalog():
    catalog = RateCard(
        source=RATE_SOURCE_CATALOG,
        rate_id=uuid4(),
        input_micro_usd_per_million=1_000_000,
        output_micro_usd_per_million=2_000_000,
        cache_read_micro_usd_per_million=500_000,
    )
    override_id = uuid4()
    merged = _merge_override_with_catalog(
        {
            "id": override_id,
            "input_micro_usd_per_million": 3_000_000,
            "output_micro_usd_per_million": None,
            "cache_read_micro_usd_per_million": None,
            "cache_creation_micro_usd_per_million": None,
            "reasoning_micro_usd_per_million": None,
            "audio_micro_usd_per_second": None,
            "tts_micro_usd_per_million_chars": None,
        },
        catalog,
    )
    assert merged.source == RATE_SOURCE_OVERRIDE
    assert merged.rate_id == override_id
    assert merged.input_micro_usd_per_million == 3_000_000
    assert merged.output_micro_usd_per_million == 2_000_000
    assert merged.cache_read_micro_usd_per_million == 500_000


def test_merge_override_without_catalog_uses_zero_defaults():
    override_id = uuid4()
    merged = _merge_override_with_catalog(
        {
            "id": override_id,
            "input_micro_usd_per_million": 100,
            "output_micro_usd_per_million": None,
            "cache_read_micro_usd_per_million": None,
            "cache_creation_micro_usd_per_million": None,
            "reasoning_micro_usd_per_million": None,
            "audio_micro_usd_per_second": None,
            "tts_micro_usd_per_million_chars": None,
        },
        None,
    )
    assert merged.input_micro_usd_per_million == 100
    assert merged.output_micro_usd_per_million == 0


def test_usd_payload_to_micro_columns():
    columns = _usd_payload_to_micro_columns(
        {
            "input_per_1m": 1.5,
            "audio_per_minute": 0.006,
        }
    )
    assert columns["input_micro_usd_per_million"] == 1_500_000
    assert columns["audio_micro_usd_per_second"] == 100
