"""Tests for Fireworks model import filter in sync_pricing_catalog_from_litellm."""

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


def test_fireworks_catalog_name_accepts_short_form_alias(sync_mod):
    key = "fireworks_ai/gpt-oss-120b"
    assert sync_mod._fireworks_catalog_name(key, _chat_cost()) == "gpt-oss-120b"


def test_fireworks_catalog_name_accepts_explicit_long_form(sync_mod):
    key = "fireworks_ai/accounts/fireworks/models/llama4-scout-instruct-basic"
    assert (
        sync_mod._fireworks_catalog_name(key, _chat_cost())
        == "llama4-scout-instruct-basic"
    )


def test_fireworks_catalog_name_skips_legacy_long_form(sync_mod):
    key = "fireworks_ai/accounts/fireworks/models/mixtral-8x22b-instruct-hf"
    assert sync_mod._fireworks_catalog_name(key, _chat_cost()) is None


def test_fireworks_catalog_name_skips_embeddings(sync_mod):
    key = "fireworks_ai/nomic-ai/nomic-embed-text-v1"
    info = {
        "mode": "embedding",
        "input_cost_per_token": 0.000000008,
        "output_cost_per_token": 0,
    }
    assert sync_mod._fireworks_catalog_name(key, info) is None


def test_fireworks_catalog_name_skips_image_models(sync_mod):
    key = "fireworks_ai/accounts/fireworks/models/flux-kontext-pro"
    info = {
        "mode": "image_generation",
        "input_cost_per_token": 0.00004,
        "output_cost_per_token": 0.00004,
    }
    assert sync_mod._fireworks_catalog_name(key, info) is None


def test_discover_missing_fireworks_models_skips_existing(sync_mod):
    model_cost = {
        "fireworks_ai/gpt-oss-120b": _chat_cost(),
        "fireworks_ai/qwen3p7-plus": _chat_cost(),
        "fireworks_ai/accounts/fireworks/models/llama4-scout-instruct-basic": _chat_cost(),
        "fireworks_ai/accounts/fireworks/models/mixtral-8x22b-instruct-hf": _chat_cost(),
        "fireworks_ai/nomic-ai/nomic-embed-text-v1": {
            "mode": "embedding",
            "input_cost_per_token": 0.000000008,
        },
    }
    existing = {
        "deepseek-v4-pro": {"provider": "fireworks", "model_type": "llm"},
        "gpt-oss-120b": {"provider": "fireworks", "model_type": "llm"},
    }
    discovered = sync_mod.discover_missing_fireworks_models(model_cost, existing)
    assert set(discovered) == {"qwen3p7-plus", "llama4-scout-instruct-basic"}


def test_insert_after_fireworks_block_preserves_existing(sync_mod):
    models = {
        "gpt-4o": {"provider": "openai", "model_type": "llm"},
        "deepseek-v4-pro": {"provider": "fireworks", "model_type": "llm"},
        "firefunction-v2": {"provider": "fireworks", "model_type": "llm"},
        "google-speech-v2": {"provider": "google", "model_type": "stt"},
    }
    new_entries = {
        "gpt-oss-120b": {"provider": "fireworks", "model_type": "llm"},
        "qwen3p7-plus": {"provider": "fireworks", "model_type": "llm"},
    }
    ordered = sync_mod._insert_after_fireworks_block(models, new_entries)
    assert list(ordered.keys()) == [
        "gpt-4o",
        "deepseek-v4-pro",
        "firefunction-v2",
        "gpt-oss-120b",
        "qwen3p7-plus",
        "google-speech-v2",
    ]
    assert ordered["deepseek-v4-pro"] == models["deepseek-v4-pro"]
