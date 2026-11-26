"""OpenTelemetry export wiring. The global tracer provider can only be set once per
process, so these tests share one provider and reset the SDK's own state between tests.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from collections.abc import Iterator, Sequence
from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SpanExportResult

from efficientai_sdk.integrations import pipecat
from efficientai_sdk.tracing import otel


class FakeOTLPExporter:
    """Stands in for OTLPSpanExporter: records headers and exported spans."""

    instances: list[FakeOTLPExporter] = []  # noqa: RUF012

    def __init__(self, *, endpoint: str, headers: dict[str, str]) -> None:
        self.endpoint = endpoint
        self.headers = headers
        self.spans: list[ReadableSpan] = []
        FakeOTLPExporter.instances.append(self)

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


@pytest.fixture(scope="module")
def provider() -> TracerProvider:
    """An app-owned provider, installed before the SDK is configured."""
    current = trace.get_tracer_provider()
    if isinstance(current, TracerProvider):
        return current
    p = TracerProvider()
    trace.set_tracer_provider(p)
    return p


@pytest.fixture(autouse=True)
def fake_exporter(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    FakeOTLPExporter.instances = []
    monkeypatch.setattr(otel, "OTLPSpanExporter", FakeOTLPExporter)
    otel._reset_for_tests()
    yield
    otel._reset_for_tests()


def latest() -> FakeOTLPExporter:
    return FakeOTLPExporter.instances[-1]


def test_create_exporter_requires_endpoint_and_key(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="EFFICIENTAI_OTLP_ENDPOINT"):
        otel.create_otlp_exporter(api_key="k")
    with pytest.raises(ValueError, match="EFFICIENTAI_API_KEY"):
        otel.create_otlp_exporter(endpoint="http://x")


def test_create_exporter_sets_correlation_headers() -> None:
    otel.create_otlp_exporter(
        endpoint="http://x/api/v1/observability/traces",
        api_key="k",
        call_short_id="482931",
        evaluator_result_id="run-1",
        workspace_id="ws-1",
        mutable=False,
    )
    assert latest().headers == {
        "X-API-Key": "k",
        "X-EfficientAI-Call-Short-Id": "482931",
        "X-EfficientAI-Run-Id": "run-1",
        "X-Workspace-Id": "ws-1",
    }


def test_mutable_exporter_is_reused_and_reconfigured() -> None:
    first = otel.create_otlp_exporter(endpoint="http://x", api_key="k", call_short_id="111111")
    second = otel.create_otlp_exporter(endpoint="http://x", api_key="k", call_short_id="222222")
    assert first is second
    assert latest().headers["X-EfficientAI-Call-Short-Id"] == "222222"


def test_call_id_read_from_sip_headers() -> None:
    otel.create_otlp_exporter(
        endpoint="http://x",
        api_key="k",
        sip_headers={"X-VH-EfficientAI-Call-Short-Id": "333333"},
        mutable=False,
    )
    assert latest().headers["X-EfficientAI-Call-Short-Id"] == "333333"


def test_setup_attaches_to_existing_provider_and_stamps_spans(provider: TracerProvider) -> None:
    ok = otel.setup_efficientai_tracing(
        call_short_id="482931",
        workspace_id="ws-1",
        agent_id="agent-1",
        transport="websocket",
        otlp_endpoint="http://x/api/v1/observability/traces",
        api_key="k",
    )
    assert ok is True

    with trace.get_tracer("test").start_as_current_span("llm"):
        pass
    assert otel.flush_efficientai_tracing() is True

    exported = latest().spans
    assert [s.name for s in exported] == ["llm"]
    attrs = dict(exported[0].attributes or {})
    assert attrs["efficientai.call_short_id"] == "482931"
    assert attrs["efficientai.agent_id"] == "agent-1"
    assert attrs["efficientai.transport"] == "websocket"


def test_second_call_updates_attributes_without_duplicate_export(
    provider: TracerProvider,
) -> None:
    common: dict[str, Any] = {"otlp_endpoint": "http://x", "api_key": "k"}
    otel.setup_efficientai_tracing(call_short_id="111111", **common)
    otel.setup_efficientai_tracing(call_short_id="222222", **common)

    with trace.get_tracer("test").start_as_current_span("tts"):
        pass
    otel.flush_efficientai_tracing()

    exported = latest().spans
    assert len(exported) == 1
    assert dict(exported[0].attributes or {})["efficientai.call_short_id"] == "222222"
    assert latest().headers["X-EfficientAI-Call-Short-Id"] == "222222"


def test_configure_pipecat_tracing_returns_task_kwargs(provider: TracerProvider) -> None:
    kwargs = pipecat.configure_pipecat_tracing(
        call_short_id="482931",
        workspace_id="ws-1",
        otlp_endpoint="http://x",
        api_key="k",
        additional_span_attributes={"custom": "1"},
    )
    assert kwargs["enable_tracing"] is True
    assert kwargs["additional_span_attributes"]["efficientai.call_short_id"] == "482931"
    assert kwargs["additional_span_attributes"]["custom"] == "1"


def test_configure_pipecat_tracing_from_handshake(provider: TracerProvider) -> None:
    kwargs = pipecat.configure_pipecat_tracing(
        handshake={
            "type": "efficientai_trace_handshake",
            "call_short_id": "654321",
            "workspace_id": "w1",
            "otel_correlation": {"otlp_endpoint": "http://x/api/v1/observability/traces"},
        },
        api_key="k",
    )
    assert kwargs["additional_span_attributes"]["efficientai.call_short_id"] == "654321"
    with pytest.raises(ValueError):
        pipecat.configure_pipecat_tracing_from_handshake({"type": "other"})


def test_works_without_opentelemetry_installed() -> None:
    """Base install: tracing imports fine, setup reports False, exporter explains the extra."""
    script = textwrap.dedent(
        """
        import sys

        class Block:
            def find_spec(self, name, path=None, target=None):
                if name == "opentelemetry" or name.startswith("opentelemetry."):
                    raise ImportError("blocked")
                return None

        sys.meta_path.insert(0, Block())
        from efficientai_sdk.tracing import (
            OTEL_AVAILABLE, create_otlp_exporter, setup_efficientai_tracing,
            flush_efficientai_tracing, extract_call_short_id,
        )
        assert OTEL_AVAILABLE is False
        assert setup_efficientai_tracing(call_short_id="123456") is False
        assert flush_efficientai_tracing() is False
        assert extract_call_short_id(webhook_params={"call_short_id": "123456"}) == "123456"
        try:
            create_otlp_exporter(endpoint="http://x", api_key="k")
        except RuntimeError as exc:
            assert "efficientai-sdk[otel]" in str(exc)
        else:
            raise AssertionError("expected RuntimeError")
        print("ok")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
