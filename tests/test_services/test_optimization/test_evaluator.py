"""Tests for GEPA optimization evaluator LM resolution."""

from types import SimpleNamespace

from app.models.enums import ModelProvider
from app.services.optimization.evaluator import _resolve_scoring_lm


def _provider(name: str, *, active: bool = True):
    return SimpleNamespace(provider=name, is_active=active, api_key="enc")


def test_resolve_scoring_lm_uses_optimization_lm_identifier():
    providers = [_provider("openai"), _provider("anthropic")]
    llm_provider, llm_model = _resolve_scoring_lm("openai/gpt-4.1", providers)

    assert llm_provider == ModelProvider.OPENAI
    assert llm_model == "gpt-4.1"


def test_resolve_scoring_lm_does_not_pair_anthropic_provider_with_openai_model():
    providers = [_provider("anthropic"), _provider("openai")]
    llm_provider, llm_model = _resolve_scoring_lm("openai/gpt-4.1", providers)

    assert llm_provider == ModelProvider.OPENAI
    assert llm_model == "gpt-4.1"


def test_resolve_scoring_lm_prefers_openai_when_lm_identifier_missing():
    providers = [_provider("anthropic"), _provider("openai")]
    llm_provider, llm_model = _resolve_scoring_lm(None, providers)

    assert llm_provider == ModelProvider.OPENAI
    assert llm_model == "gpt-4o-mini"
