"""Unit tests for EfficientAI tracing bootstrap."""

from types import SimpleNamespace

import pytest

from app.services.tracing import efficientai_otel as otel


@pytest.fixture(autouse=True)
def _reset_initialized_flag():
    otel._INITIALIZED = False
    yield
    otel._INITIALIZED = False


def test_provider_uses_zero_sample_rate(monkeypatch):
    created = {}

    class FakeTracerProvider:
        def __init__(self, resource=None, sampler=None):
            self.resource = resource
            self.sampler = sampler

    monkeypatch.setattr(otel, "OTEL_AVAILABLE", True)
    monkeypatch.setattr(otel, "TracerProvider", FakeTracerProvider)
    monkeypatch.setattr(otel, "Resource", SimpleNamespace(create=lambda attrs: attrs))
    monkeypatch.setattr(otel, "ParentBased", lambda root: ("parent", root))
    monkeypatch.setattr(otel, "TraceIdRatioBased", lambda rate: ("ratio", rate))
    monkeypatch.setattr(
        otel,
        "trace",
        SimpleNamespace(
            get_tracer_provider=lambda: object(),
            set_tracer_provider=lambda provider: created.setdefault("provider", provider),
        ),
    )
    monkeypatch.setattr(otel.settings, "OBSERVABILITY_TRACING_SAMPLE_RATE", 0.0)

    provider = otel._get_or_create_provider("efficientai-test")

    assert isinstance(provider, FakeTracerProvider)
    assert provider.sampler == ("parent", ("ratio", 0.0))
    assert created["provider"] is provider


def test_provider_uses_full_sample_rate(monkeypatch):
    class FakeTracerProvider:
        def __init__(self, resource=None, sampler=None):
            self.resource = resource
            self.sampler = sampler

    monkeypatch.setattr(otel, "OTEL_AVAILABLE", True)
    monkeypatch.setattr(otel, "TracerProvider", FakeTracerProvider)
    monkeypatch.setattr(otel, "Resource", SimpleNamespace(create=lambda attrs: attrs))
    monkeypatch.setattr(otel, "ParentBased", lambda root: ("parent", root))
    monkeypatch.setattr(otel, "TraceIdRatioBased", lambda rate: ("ratio", rate))
    monkeypatch.setattr(
        otel,
        "trace",
        SimpleNamespace(
            get_tracer_provider=lambda: object(),
            set_tracer_provider=lambda provider: None,
        ),
    )
    monkeypatch.setattr(otel.settings, "OBSERVABILITY_TRACING_SAMPLE_RATE", 1.0)

    provider = otel._get_or_create_provider("efficientai-test")

    assert isinstance(provider, FakeTracerProvider)
    assert provider.sampler == ("parent", ("ratio", 1.0))
