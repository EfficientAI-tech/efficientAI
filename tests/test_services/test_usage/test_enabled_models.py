"""Tests for org/credential enabled model allowlists."""

from uuid import uuid4

from app.services.usage.enabled_models import (
    filter_models_by_credential,
    normalize_enabled_models,
    org_pricing_eligible_models,
)


class _Credential:
    def __init__(self, *, enabled_models=None, gateway_model=None, provider="openai"):
        self.enabled_models = enabled_models
        self.gateway_model = gateway_model
        self.provider = provider


def test_normalize_enabled_models_dedupes_and_trims():
    assert normalize_enabled_models([" gpt-4o ", "gpt-4o", ""]) == ["gpt-4o"]


def test_filter_models_by_credential_restricts_catalog():
    cred = _Credential(enabled_models=["gpt-4o"])
    assert filter_models_by_credential(cred, ["gpt-4o", "gpt-5-mini"]) == ["gpt-4o"]


def test_filter_models_by_credential_includes_gateway_model():
    cred = _Credential(enabled_models=["gpt-4o"], gateway_model="custom/deploy")
    assert filter_models_by_credential(cred, ["gpt-4o"]) == ["custom/deploy", "gpt-4o"]


def test_filter_models_unrestricted_when_allowlist_empty():
    cred = _Credential(enabled_models=None)
    assert filter_models_by_credential(cred, ["a", "b"]) == ["a", "b"]


def test_org_pricing_eligible_models_includes_usage_and_overrides(monkeypatch):
    org_id = uuid4()

    class FakeResult:
        def scalars(self):
            return self

        def all(self):
            return ["used-model"]

    class FakeDb:
        def execute(self, *_args, **_kwargs):
            return FakeResult()

        def query(self, *_args, **_kwargs):
            return self

        def filter(self, *_args, **_kwargs):
            return self

        def all(self):
            return []

    monkeypatch.setattr(
        "app.services.usage.enabled_models.catalog_models_for_provider",
        lambda _provider: ["catalog-model"],
    )
    models = org_pricing_eligible_models(FakeDb(), org_id)
    assert "used-model" in models
