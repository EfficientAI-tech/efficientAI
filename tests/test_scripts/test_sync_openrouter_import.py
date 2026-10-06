"""Tests for OpenRouter catalog import in sync_openrouter_models."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SYNC_SCRIPT = REPO_ROOT / "scripts" / "sync_openrouter_models.py"


def _load_sync_module():
    spec = importlib.util.spec_from_file_location("sync_openrouter_models", SYNC_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(name="sync_mod")
def fixture_sync_mod():
    return _load_sync_module()


def test_pricing_from_openrouter_converts_per_token_to_per_million(sync_mod):
    pricing = sync_mod.pricing_from_openrouter(
        {
            "prompt": "0.0000025",
            "completion": "0.00001",
            "input_cache_read": "0",
            "internal_reasoning": "0.000005",
        }
    )
    assert pricing["source"] == "openrouter_import"
    assert pricing["usage_kind"] == "llm"
    assert pricing["input_per_1m"] == pytest.approx(2.5)
    assert pricing["output_per_1m"] == pytest.approx(10.0)
    assert pricing["cache_read_per_1m"] == pytest.approx(0.0)
    assert pricing["reasoning_per_1m"] == pytest.approx(5.0)


def test_should_include_openrouter_model_requires_text_output(sync_mod):
    chat = {
        "id": "anthropic/claude-sonnet-4",
        "architecture": {"output_modalities": ["text"]},
    }
    embed = {
        "id": "openai/text-embedding-3-large",
        "architecture": {"output_modalities": ["text"]},
    }
    image_only = {
        "id": "some/image-gen",
        "architecture": {"output_modalities": ["image"]},
    }
    assert sync_mod.should_include_openrouter_model(chat) is True
    assert sync_mod.should_include_openrouter_model(embed) is False
    assert sync_mod.should_include_openrouter_model(image_only) is False


def test_apply_manual_openrouter_models_includes_jev(sync_mod):
    entries = sync_mod.apply_manual_openrouter_models({})
    assert "typesafe/jev-1.13" in entries
    jev = entries["typesafe/jev-1.13"]
    assert jev["provider"] == "openrouter"
    assert jev["pricing"]["input_per_1m"] == pytest.approx(0.04)
    assert jev["pricing"]["output_per_1m"] == pytest.approx(0.0)


def test_merge_openrouter_into_models_replaces_openrouter_only(sync_mod):
    models = {
        "gpt-4o": {"provider": "openai", "model_type": "llm"},
        "anthropic/claude-3.5-sonnet": {
            "provider": "openrouter",
            "model_type": "llm",
        },
        "whisper-1": {"provider": "openai", "model_type": "stt"},
    }
    new_entries = {
        "openai/gpt-4o": {
            "provider": "openrouter",
            "model_type": "llm",
            "description": "via OpenRouter",
        },
        "gpt-4o": {
            "provider": "openrouter",
            "model_type": "llm",
            "description": "should not clobber",
        },
    }
    merged = sync_mod.merge_openrouter_into_models(models, new_entries)
    assert merged["gpt-4o"]["provider"] == "openai"
    assert "anthropic/claude-3.5-sonnet" not in merged
    assert merged["openai/gpt-4o"]["provider"] == "openrouter"
    assert merged["whisper-1"]["provider"] == "openai"
