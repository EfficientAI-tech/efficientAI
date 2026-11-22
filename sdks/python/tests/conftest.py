from __future__ import annotations

import pytest

from efficientai_sdk import _base_client
from efficientai_sdk._config import ENV_API_KEY, ENV_BASE_URL, ENV_BASE_URL_LEGACY, ENV_WORKSPACE_ID

BASE_URL = "https://api.test"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests must not pick up a developer's real EFFICIENTAI_* settings."""
    for name in (ENV_API_KEY, ENV_WORKSPACE_ID, ENV_BASE_URL, ENV_BASE_URL_LEGACY):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record retry sleeps instead of waiting."""
    recorded: list[float] = []

    async def fake_async_sleep(delay: float) -> None:
        recorded.append(delay)

    monkeypatch.setattr(_base_client.time, "sleep", recorded.append)
    monkeypatch.setattr(_base_client.asyncio, "sleep", fake_async_sleep)
    return recorded


# ---- OpenTelemetry -------------------------------------------------------
# The global tracer provider can only be set once per process, so all tests share one
# provider. An in-memory exporter captures every finished span.

from collections.abc import Iterator  # noqa: E402

from opentelemetry import trace  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)

from efficientai_sdk.tracing import context as call_context  # noqa: E402
from efficientai_sdk.tracing import otel  # noqa: E402

_MEMORY = InMemorySpanExporter()


def _install_provider() -> TracerProvider:
    current = trace.get_tracer_provider()
    if isinstance(current, TracerProvider):
        return current
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(_MEMORY))
    trace.set_tracer_provider(provider)
    return provider


@pytest.fixture(scope="session")
def provider() -> TracerProvider:
    """An app-owned provider, installed before the SDK is configured."""
    return _install_provider()


@pytest.fixture
def spans(provider: TracerProvider) -> Iterator[InMemorySpanExporter]:
    _MEMORY.clear()
    yield _MEMORY
    _MEMORY.clear()


@pytest.fixture(autouse=True)
def _isolate_tracing_state() -> Iterator[None]:
    """No call context or exporter state leaks between tests."""
    call_context._CALL_ATTRIBUTES.set(None)
    otel._reset_for_tests()
    yield
    call_context._CALL_ATTRIBUTES.set(None)
    otel._reset_for_tests()
