from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from typing import Any

import httpx
import pytest
import respx
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from efficientai_sdk import AsyncEfficientAI, EfficientAI
from efficientai_sdk.integrations import pipecat
from efficientai_sdk.tracing import (
    TraceSessionError,
    get_call_attributes,
    otel,
    setup_worker_tracing,
)

BASE = "http://eai.test"
SESSIONS = f"{BASE}/api/v1/observability/traces/sessions"


class FakeOTLPExporter:
    instances: list[FakeOTLPExporter] = []  # noqa: RUF012

    def __init__(self, *, endpoint: str, headers: dict[str, str]) -> None:
        self.endpoint = endpoint
        self.headers = headers
        FakeOTLPExporter.instances.append(self)

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


@pytest.fixture(autouse=True)
def fake_exporter(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeOTLPExporter.instances = []
    monkeypatch.setattr(otel, "OTLPSpanExporter", FakeOTLPExporter)


def session_json(call_short_id: str = "482931", **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "trace_id": "t-1",
        "call_short_id": call_short_id,
        "workspace_id": "ws-1",
        "transport": "websocket",
        "status": "open",
        "otel_correlation": {"otlp_endpoint": f"{BASE}/api/v1/observability/traces"},
    }
    body.update(extra)
    return body


def sync_client() -> EfficientAI:
    return EfficientAI(api_key="key", workspace_id="ws-1", base_url=BASE)


def async_client() -> AsyncEfficientAI:
    return AsyncEfficientAI(api_key="key", workspace_id="ws-1", base_url=BASE)


def attrs_of(span: ReadableSpan) -> dict[str, Any]:
    return dict(span.attributes or {})


# ---- sync session --------------------------------------------------------


@respx.mock
def test_sync_session_emits_mapper_compatible_spans(spans: InMemorySpanExporter) -> None:
    mint = respx.post(SESSIONS).respond(200, json=session_json())
    close = respx.post(f"{SESSIONS}/482931/close").respond(200, json={})
    client = sync_client()

    with client.trace.session(transport="websocket", agent_id="agent-1") as call:
        assert call.enabled and call.call_short_id == "482931"
        assert get_call_attributes() == call.attributes
        with call.turn() as turn:
            turn.set_user_bot_latency(0.9)
            with call.stt(model="nova-3", provider="Deepgram") as stt:
                stt.set_transcript("book a table")
            with call.llm(model="gpt-4o", provider="openai") as llm:
                llm.set_output("For how many?").set_ttfb(0.31)
            with call.tts(model="sonic", provider="cartesia", text="For how many?"):
                pass

    assert get_call_attributes() is None
    assert json.loads(mint.calls.last.request.content) == {
        "transport": "websocket",
        "agent_id": "agent-1",
    }
    assert close.called

    by_name = {s.name: attrs_of(s) for s in spans.get_finished_spans()}
    assert set(by_name) == {"turn", "stt", "llm", "tts"}
    for attrs in by_name.values():
        assert attrs["efficientai.call_short_id"] == "482931"
        assert attrs["efficientai.agent_id"] == "agent-1"
        assert attrs["efficientai.workspace_id"] == "ws-1"
    assert by_name["turn"]["turn.number"] == 1
    assert by_name["turn"]["turn.user_bot_latency_seconds"] == 0.9
    assert by_name["stt"]["gen_ai.operation.name"] == "stt"
    assert by_name["stt"]["gen_ai.provider.name"] == "deepgram"
    assert by_name["stt"]["transcript"] == "book a table"
    assert by_name["llm"]["gen_ai.operation.name"] == "chat"
    assert by_name["llm"]["gen_ai.request.model"] == "gpt-4o"
    assert by_name["llm"]["output"] == "For how many?"
    assert by_name["llm"]["metrics.ttfb"] == 0.31
    assert by_name["tts"]["text"] == "For how many?"

    parents = {s.name: s.parent.span_id if s.parent else None for s in spans.get_finished_spans()}
    turn_id = next(s for s in spans.get_finished_spans() if s.name == "turn").context.span_id
    assert parents["stt"] == parents["llm"] == parents["tts"] == turn_id


@respx.mock
def test_export_pipeline_uses_session_endpoint_and_no_call_header(provider: Any) -> None:
    respx.post(SESSIONS).respond(200, json=session_json())
    respx.post(f"{SESSIONS}/482931/close").respond(200, json={})
    with sync_client().trace.session():
        pass
    exporter = FakeOTLPExporter.instances[-1]
    assert exporter.endpoint == f"{BASE}/api/v1/observability/traces"
    assert exporter.headers == {"X-API-Key": "key", "X-Workspace-Id": "ws-1"}


@respx.mock
def test_pipeline_is_created_once_for_many_calls(provider: Any) -> None:
    respx.post(SESSIONS).respond(200, json=session_json())
    respx.post(f"{SESSIONS}/482931/close").respond(200, json={})
    client = sync_client()
    for _ in range(3):
        with client.trace.session():
            pass
    assert len(FakeOTLPExporter.instances) == 1
    assert client.trace.instrument() is True
    assert len(FakeOTLPExporter.instances) == 1


@respx.mock
def test_turn_numbers_increment(spans: InMemorySpanExporter) -> None:
    respx.post(SESSIONS).respond(200, json=session_json())
    respx.post(f"{SESSIONS}/482931/close").respond(200, json={})
    with sync_client().trace.session() as call:
        for _ in range(3):
            with call.turn():
                pass
    numbers = [attrs_of(s)["turn.number"] for s in spans.get_finished_spans()]
    assert numbers == [1, 2, 3]


# ---- reusing the platform's call id --------------------------------------


@respx.mock
def test_handshake_session_skips_mint_and_close(spans: InMemorySpanExporter) -> None:
    mint = respx.post(SESSIONS).respond(200, json=session_json())
    close = respx.post(f"{SESSIONS}/123456/close").respond(200, json={})
    handshake = {
        "type": "efficientai_trace_handshake",
        "call_short_id": "123456",
        "agent_id": "a1",
        "workspace_id": "w1",
        "transport": "webrtc",
        "otel_correlation": {
            "otlp_endpoint": f"{BASE}/api/v1/observability/traces",
            "suggested_span_attributes": {"efficientai.evaluator_result_id": "run-7"},
        },
    }
    with sync_client().trace.session(handshake=handshake) as call, call.llm(output="hi"):
        pass
    assert not mint.called
    assert not close.called
    attrs = attrs_of(spans.get_finished_spans()[0])
    assert attrs["efficientai.call_short_id"] == "123456"
    assert attrs["efficientai.evaluator_result_id"] == "run-7"
    assert attrs["efficientai.transport"] == "webrtc"
    assert attrs["efficientai.workspace_id"] == "w1"


@respx.mock
def test_http_headers_from_platform(spans: InMemorySpanExporter) -> None:
    mint = respx.post(SESSIONS).respond(200, json=session_json())
    headers = {"X-EfficientAI-Call-Short-Id": "654321", "X-EfficientAI-Run-Id": "run-2"}
    with sync_client().trace.session(headers=headers) as call:
        assert call.call_short_id == "654321"
        assert call.evaluator_result_id == "run-2"
    assert not mint.called


def test_sip_headers_from_platform() -> None:
    sip = {"X-VH-EfficientAI-Call-Short-Id": "111222"}
    with sync_client().trace.session(sip_headers=sip, transport="phone") as call:
        assert call.call_short_id == "111222"
        assert call.transport == "phone"


# ---- failure handling ----------------------------------------------------


@respx.mock
def test_session_failure_disables_tracing(spans: InMemorySpanExporter, sleeps: list[float]) -> None:
    respx.post(SESSIONS).respond(401, json={"detail": "Invalid API key"})
    with sync_client().trace.session() as call:
        assert call.enabled is False
        assert "Invalid API key" in (call.error or "")
        with call.turn() as turn, call.llm() as llm:
            turn.set_interrupted()
            llm.set_output("ignored")
        assert call.attributes == {}
        assert pipecat.task_kwargs(call) == {}
    assert spans.get_finished_spans() == ()


@respx.mock
def test_session_failure_strict_raises() -> None:
    respx.post(SESSIONS).respond(500)
    with pytest.raises(TraceSessionError) as info, sync_client().trace.session(strict=True):
        pass
    assert info.value.status_code == 500


@respx.mock
def test_user_exception_propagates_and_is_recorded(spans: InMemorySpanExporter) -> None:
    respx.post(SESSIONS).respond(200, json=session_json())
    close = respx.post(f"{SESSIONS}/482931/close").respond(200, json={})
    client = sync_client()
    with pytest.raises(RuntimeError, match="boom"), client.trace.session() as call, call.llm():
        raise RuntimeError("boom")
    span = spans.get_finished_spans()[0]
    assert span.status.status_code == StatusCode.ERROR
    assert close.called  # session still closed


@respx.mock
def test_close_failure_does_not_raise(sleeps: list[float]) -> None:
    respx.post(SESSIONS).respond(200, json=session_json())
    respx.post(f"{SESSIONS}/482931/close").mock(side_effect=httpx.ConnectError("down"))
    with sync_client().trace.session():
        pass


def test_invalid_transport_is_a_programming_error() -> None:
    with pytest.raises(ValueError), sync_client().trace.session(transport="carrier-pigeon"):
        pass


# ---- async + concurrency -------------------------------------------------


@respx.mock
async def test_async_session(spans: InMemorySpanExporter) -> None:
    respx.post(SESSIONS).respond(200, json=session_json())
    close = respx.post(f"{SESSIONS}/482931/close").respond(200, json={})
    client = async_client()
    async with client.trace.session(transport="webrtc") as call:
        with call.turn(), call.s2s(model="gpt-realtime", provider="openai") as s2s:
            s2s.set_output("hello")
    assert close.called
    names = sorted(s.name for s in spans.get_finished_spans())
    assert names == ["s2s", "turn"]


@respx.mock
async def test_concurrent_calls_tag_their_own_spans(spans: InMemorySpanExporter) -> None:
    """Spans created by any code (not just SDK helpers) carry their own call's id."""
    ids = iter(["111111", "222222"])
    respx.post(SESSIONS).mock(
        side_effect=lambda req: httpx.Response(200, json=session_json(next(ids)))
    )
    respx.post(url__regex=rf"{SESSIONS}/\d+/close").respond(200, json={})
    client = async_client()
    tracer = trace.get_tracer("framework")

    async def handle_call(label: str) -> str:
        async with client.trace.session(transport="websocket") as call:
            for i in range(3):
                with tracer.start_as_current_span(f"{label}-{i}"):
                    await asyncio.sleep(0)  # interleave with the other call

                async def background(n: int) -> None:
                    with tracer.start_as_current_span(f"{label}-bg-{n}"):
                        await asyncio.sleep(0)

                await asyncio.create_task(background(i))
            return call.call_short_id or ""

    call_a, call_b = await asyncio.gather(handle_call("a"), handle_call("b"))
    assert {call_a, call_b} == {"111111", "222222"}
    owners = {"a": call_a, "b": call_b}
    finished = spans.get_finished_spans()
    assert len(finished) == 12
    for span in finished:
        assert attrs_of(span)["efficientai.call_short_id"] == owners[span.name[0]]


async def test_legacy_setup_is_also_per_task(spans: InMemorySpanExporter) -> None:
    """setup_worker_tracing (pre-SDK API) no longer mixes concurrent calls."""
    tracer = trace.get_tracer("framework")

    async def worker(call_id: str) -> None:
        setup_worker_tracing(
            {
                "enabled": True,
                "call_short_id": call_id,
                "workspace_id": "ws-1",
                "otlp_endpoint": "http://x/api/v1/observability/traces",
            }
        )
        for _ in range(3):
            with tracer.start_as_current_span(call_id):
                await asyncio.sleep(0)

    import os

    os.environ["EFFICIENTAI_API_KEY"] = "key"
    try:
        await asyncio.gather(worker("333333"), worker("444444"))
    finally:
        del os.environ["EFFICIENTAI_API_KEY"]
    for span in spans.get_finished_spans():
        assert attrs_of(span)["efficientai.call_short_id"] == span.name


@respx.mock
async def test_activate_tags_work_in_other_threads(spans: InMemorySpanExporter) -> None:
    respx.post(SESSIONS).respond(200, json=session_json())
    respx.post(f"{SESSIONS}/482931/close").respond(200, json={})
    client = async_client()
    tracer = trace.get_tracer("framework")
    async with client.trace.session() as call:

        def in_thread() -> None:
            with call.activate(), tracer.start_as_current_span("thread-work"):
                pass

        await asyncio.get_running_loop().run_in_executor(None, in_thread)
    span = spans.get_finished_spans()[0]
    assert attrs_of(span)["efficientai.call_short_id"] == "482931"


# ---- resume a platform call ------------------------------------------------


@respx.mock
def test_resume_helpers_reuse_platform_call_id() -> None:
    mint = respx.post(SESSIONS).respond(200, json=session_json("999999"))
    client = sync_client()

    with client.trace.from_request(
        {"X-EfficientAI-Call-Short-Id": "165730", "X-EfficientAI-Run-Id": "run-1"}
    ) as call:
        assert call.call_short_id == "165730"
        assert call.evaluator_result_id == "run-1"
        assert call.owns_session is False

    with client.trace.from_sip_headers({"X-VH-EfficientAI-Call-Short-Id": "569762"}) as call:
        assert call.call_short_id == "569762"

    with client.trace.from_handshake(
        {"type": "efficientai_trace_handshake", "call_short_id": "611725", "transport": "webrtc"}
    ) as call:
        assert call.call_short_id == "611725"
        assert call.transport == "webrtc"

    assert mint.called is False


# ---- pipecat ---------------------------------------------------------------


@respx.mock
def test_pipecat_task_kwargs() -> None:
    respx.post(SESSIONS).respond(200, json=session_json())
    respx.post(f"{SESSIONS}/482931/close").respond(200, json={})
    with sync_client().trace.session(transport="webrtc") as call:
        kwargs = pipecat.task_kwargs(call, **{"app.version": "1.2"})
    assert kwargs["enable_tracing"] is True
    assert kwargs["additional_span_attributes"]["efficientai.call_short_id"] == "482931"
    assert kwargs["additional_span_attributes"]["app.version"] == "1.2"
