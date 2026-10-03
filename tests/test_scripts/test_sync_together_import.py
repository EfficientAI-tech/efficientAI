"""Tests for Together model import filter in sync_pricing_catalog_from_litellm."""

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
        "input_cost_per_token": 0.000000042,
        "output_cost_per_token": 0.0,
    }
    base.update(overrides)
    return base


def test_together_catalog_name_accepts_slash_slug(sync_mod):
    key = "together_ai/meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo"
    assert (
        sync_mod._together_catalog_name(key, _chat_cost())
        == "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo"
    )


def test_together_catalog_name_accepts_tev1(sync_mod):
    key = "together_ai/together/Tev1-4B-experimental"
    assert (
        sync_mod._together_catalog_name(key, _chat_cost())
        == "together/Tev1-4B-experimental"
    )


def test_together_catalog_name_skips_embeddings(sync_mod):
    key = "together_ai/togethercomputer/m2-bert-80M-8k-retrieval"
    info = {
        "mode": "embedding",
        "input_cost_per_token": 0.000000008,
        "output_cost_per_token": 0,
    }
    assert sync_mod._together_catalog_name(key, info) is None


def test_discover_missing_together_models_skips_existing(sync_mod):
    model_cost = {
        "together_ai/meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo": _chat_cost(),
        "together_ai/together/Tev1-4B-experimental": _chat_cost(),
        "together_ai/togethercomputer/m2-bert-80M-8k-retrieval": {
            "mode": "embedding",
            "input_cost_per_token": 0.000000008,
        },
    }
    existing = {
        "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo": {
            "provider": "together",
            "model_type": "llm",
        },
    }
    discovered = sync_mod.discover_missing_together_models(model_cost, existing)
    assert set(discovered) == {"together/Tev1-4B-experimental"}


def test_insert_after_together_block_preserves_existing(sync_mod):
    models = {
        "gpt-4o": {"provider": "openai", "model_type": "llm"},
        "deepseek-v4-pro": {"provider": "fireworks", "model_type": "llm"},
        "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo": {
            "provider": "together",
            "model_type": "llm",
        },
        "google-speech-v2": {"provider": "google", "model_type": "stt"},
    }
    new_entries = {
        "together/Tev1-4B-experimental": {"provider": "together", "model_type": "llm"},
    }
    ordered = sync_mod._insert_after_together_block(models, new_entries)
    assert list(ordered.keys()) == [
        "gpt-4o",
        "deepseek-v4-pro",
        "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
        "together/Tev1-4B-experimental",
        "google-speech-v2",
    ]
