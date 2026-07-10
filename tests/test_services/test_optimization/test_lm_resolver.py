"""Tests for optimization LM resolver helpers."""

import importlib
from types import SimpleNamespace
from uuid import uuid4

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
        SimpleNamespace(
            id=uuid4(),
            provider="openai",
            api_key="enc-1",
            is_active=True,
            is_default=True,
            routing_mode="inherit",
            gateway_model=None,
        ),
        SimpleNamespace(
            id=uuid4(),
            provider="anthropic",
            api_key="enc-2",
            is_active=True,
            is_default=True,
            routing_mode="inherit",
            gateway_model=None,
        ),
    ]
    monkeypatch.setattr(
        resolver_module,
        "resolve_litellm_api_key",
        lambda _org_id, _db, provider, credential=None: f"dec::{provider.api_key}",
    )

    org_id = uuid4()
    db = SimpleNamespace()
    assert (
        resolver_module.resolve_api_key("openai/gpt-4o", providers, org_id, db)
        == "dec::enc-1"
    )


def test_resolve_api_key_raises_for_missing_provider():
    providers = [
        SimpleNamespace(
            id=uuid4(),
            provider="anthropic",
            api_key="enc-2",
            is_active=True,
            is_default=True,
            routing_mode="inherit",
            gateway_model=None,
        )
    ]
    org_id = uuid4()
    db = SimpleNamespace()
    with pytest.raises(RuntimeError, match="No active AI provider"):
        resolver_module.resolve_api_key("openai/gpt-4o", providers, org_id, db)


def test_resolve_lm_call_uses_gateway_model(monkeypatch):
    credential_id = uuid4()
    providers = [
        SimpleNamespace(
            id=credential_id,
            provider="openai",
            api_key="enc-1",
            is_active=True,
            is_default=True,
            routing_mode="gateway",
            gateway_model="production-gpt4",
        ),
    ]
    bundle = SimpleNamespace(
        llm_provider="openai",
        llm_model="gpt-4o",
        llm_credential_id=credential_id,
    )
    monkeypatch.setattr(
        resolver_module,
        "resolve_litellm_api_key",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        resolver_module,
        "resolve_effective_routing",
        lambda *_args, **_kwargs: (object(), "bifrost"),
    )

    model_str, api_key, ctx = resolver_module.resolve_lm_call(
        bundle,
        None,
        providers,
        uuid4(),
        SimpleNamespace(),
    )
    assert model_str == "production-gpt4"
    assert api_key is None
    assert ctx.gateway_model == "production-gpt4"
