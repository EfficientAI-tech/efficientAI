"""Tests for TypeSafe model import filter in sync_pricing_catalog_from_litellm."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SYNC_SCRIPT = REPO_ROOT / "scripts" / "sync_pricing_catalog_from_litellm.py"


def _load_sync_module():
    spec = importlib.util.spec_from_file_location(
        "sync_pricing_catalog_from_litellm", SYNC_SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(name="sync_mod")
def fixture_sync_mod():
    return _load_sync_module()


def _chat_cost(**overrides):
    base = {
        "mode": "chat",
        "input_cost_per_token": 0.00000015,
        "output_cost_per_token": 0.0000006,
    }
    base.update(overrides)
    return base


def test_typesafe_catalog_name_accepts_jev_slug(sync_mod):
    key = "typesafe/jev-1.13.0"
    assert sync_mod._typesafe_catalog_name(key, _chat_cost()) == "jev-1.13.0"


def test_typesafe_catalog_name_accepts_evaluation_mode(sync_mod):
    key = "typesafe/jev-1.13.0"
    info = {
        "mode": "evaluation",
        "input_cost_per_token": 0.000000042,
        "output_cost_per_token": 0.0,
    }
    assert sync_mod._typesafe_catalog_name(key, info) == "jev-1.13.0"


def test_typesafe_catalog_name_skips_embeddings(sync_mod):
    key = "typesafe/jev-embed-v1"
    info = {
        "mode": "embedding",
        "input_cost_per_token": 0.000000008,
        "output_cost_per_token": 0,
    }
    assert sync_mod._typesafe_catalog_name(key, info) is None


def test_discover_missing_typesafe_models_skips_existing(sync_mod):
    model_cost = {
        "typesafe/jev-1.13.0": _chat_cost(),
        "typesafe/jev-1.12.0": _chat_cost(),
    }
    existing = {
        "jev-1.13.0": {"provider": "typesafe", "model_type": "llm"},
    }
    discovered = sync_mod.discover_missing_typesafe_models(model_cost, existing)
    assert set(discovered) == {"jev-1.12.0"}
