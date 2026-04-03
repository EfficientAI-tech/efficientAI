"""Tests for optimization LM resolver helpers."""

import importlib
from types import SimpleNamespace

import pytest

resolver_module = importlib.import_module("app.services.optimization.lm_resolver")


def test_resolve_lm_prioritizes_voice_bundle_then_evaluator_then_default():
    bundle = SimpleNamespace(llm_provider="openai", llm_model="gpt-4o-mini")
    evaluator = SimpleNamespace(llm_provider="anthropic", llm_model="claude-3-5-sonnet")
    assert resolver_module.resolve_lm(bundle, evaluator) == "openai/gpt-4o-mini"

    no_bundle = SimpleNamespace(llm_provider=None, llm_model=None)
    assert resolver_module.resolve_lm(no_bundle, evaluator) == "anthropic/claude-3-5-sonnet"
    assert resolver_module.resolve_lm(None, None) == "openai/gpt-4o"


def test_resolve_api_key_returns_decrypted_key(monkeypatch):
    providers = [
        SimpleNamespace(provider="openai", api_key="enc-1", is_active=True),
        SimpleNamespace(provider="anthropic", api_key="enc-2", is_active=True),
    ]
    monkeypatch.setattr(resolver_module, "decrypt_api_key", lambda v: f"dec::{v}")

    assert resolver_module.resolve_api_key("openai/gpt-4o", providers) == "dec::enc-1"


def test_resolve_api_key_raises_for_missing_provider():
    providers = [SimpleNamespace(provider="anthropic", api_key="enc-2", is_active=True)]
    with pytest.raises(RuntimeError, match="No active AI provider"):
        resolver_module.resolve_api_key("openai/gpt-4o", providers)
