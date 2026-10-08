"""Tests for usage pricing ops helpers."""

from __future__ import annotations

from app.services.usage.pricing_ops import (
    models_missing_pricing_blocks,
    pricing_catalog_needs_seed,
)


def test_models_missing_pricing_blocks_is_sorted_list():
    missing = models_missing_pricing_blocks()
    assert missing == sorted(missing)


def test_pricing_catalog_needs_seed_when_new_models_or_mismatches():
    assert not pricing_catalog_needs_seed(
        {"only_in_models_json": [], "mismatches": []}
    )
    assert pricing_catalog_needs_seed(
        {"only_in_models_json": [{"model": "together/Tev1-4B-experimental", "usage_kind": "llm"}], "mismatches": []}
    )
    assert pricing_catalog_needs_seed(
        {
            "only_in_models_json": [],
            "mismatches": [{"model": "gpt-4o", "usage_kind": "llm", "fields": {}}],
        }
    )
    assert not pricing_catalog_needs_seed(
        {
            "only_in_models_json": [],
            "mismatches": [],
            "only_in_database": [{"model": "legacy-model", "usage_kind": "llm"}],
        }
    )
