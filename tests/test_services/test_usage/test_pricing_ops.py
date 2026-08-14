"""Tests for usage pricing ops helpers."""

from __future__ import annotations

from app.services.usage.pricing_ops import models_missing_pricing_blocks


def test_models_missing_pricing_blocks_is_sorted_list():
    missing = models_missing_pricing_blocks()
    assert missing == sorted(missing)
