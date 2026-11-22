from __future__ import annotations

from typing import Any

import pytest
import respx
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from efficientai_sdk import EfficientAI
from efficientai_sdk.tracing import api, otel

BASE = "http://eai.test"
SESSIONS = f"{BASE}/api/v1/observability/traces/sessions"


@pytest.fixture(autouse=True)
def no_network_export(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(otel, "ensure_export_pipeline", lambda **_: True)


@pytest.fixture
def mocked_session() -> Any:
    with respx.mock:
        respx.post(SESSIONS).respond(
            200, json={"call_short_id": "482931", "workspace_id": "ws-1", "trace_id": "t"}
        )
        respx.post(f"{SESSIONS}/482931/close").respond(200, json={})
        yield


def client() -> EfficientAI:
    return EfficientAI(api_key="key", workspace_id="ws-1", base_url=BASE)


def by_name(spans: InMemorySpanExporter) -> dict[str, ReadableSpan]:
    return {s.name: s for s in spans.get_finished_spans()}


def test_chat_helpers_emit_expected_spans(spans: InMemorySpanExporter, mocked_session: Any) -> None:
    with client().trace.session(channel="chat") as call:
        assert call.attributes["efficientai.channel"] == "chat"
        with call.turn():
            call.user_message("Where is my order?")
            with call.tool("lookup_order", arguments='{"id": 1}') as tool:
                tool.set_result('{"status": "shipped"}')
            with call.retrieval(source="faq", query="shipping") as kb:
                kb.set_documents(3)
            with call.llm(model="gpt-4o", output="It shipped."):
                pass
            call.assistant_message("It shipped yesterday.")

    found = by_name(spans)
    assert set(found) == {
        "turn",
        "user_message",
        "execute_tool lookup_order",
        "retrieval",
        "llm",
        "assistant_message",
    }
    for s in found.values():
        assert (s.attributes or {})["efficientai.channel"] == "chat"

    user = dict(found["user_message"].attributes or {})
    assert user["gen_ai.operation.name"] == "user_message"
    assert user["message"] == "Where is my order?"
    assert found["user_message"].end_time == found["user_message"].start_time or (
        (found["user_message"].end_time or 0) - (found["user_message"].start_time or 0) < 5_000_000
    )

    tool = dict(found["execute_tool lookup_order"].attributes or {})
    assert tool["gen_ai.operation.name"] == "execute_tool"
    assert tool["gen_ai.tool.name"] == "lookup_order"
    assert tool["gen_ai.tool.call.arguments"] == '{"id": 1}'
    assert tool["gen_ai.tool.call.result"] == '{"status": "shipped"}'

    kb = dict(found["retrieval"].attributes or {})
    assert kb["retrieval.source"] == "faq"
    assert kb["retrieval.query"] == "shipping"
    assert kb["retrieval.documents.count"] == 3

    assert dict(found["assistant_message"].attributes or {})["message"] == "It shipped yesterday."


def test_tool_error_is_recorded(spans: InMemorySpanExporter, mocked_session: Any) -> None:
    with client().trace.session(channel="chat") as call:
        with call.tool("charge_card") as tool:
            tool.set_error("card declined")
        with pytest.raises(TimeoutError), call.tool("slow_api"):
            raise TimeoutError

    found = by_name(spans)
    assert dict(found["execute_tool charge_card"].attributes or {})["error"] is True
    assert found["execute_tool slow_api"].status.status_code == StatusCode.ERROR


def test_long_values_are_truncated(spans: InMemorySpanExporter, mocked_session: Any) -> None:
    huge = "x" * (api.MAX_ATTRIBUTE_CHARS + 500)
    with client().trace.session(channel="chat") as call, call.tool("dump") as tool:
        tool.set_result(huge)
    result = dict(by_name(spans)["execute_tool dump"].attributes or {})["gen_ai.tool.call.result"]
    assert isinstance(result, str)
    assert len(result) < len(huge)
    assert result.endswith("...[truncated]")


def test_voice_sessions_have_no_channel(spans: InMemorySpanExporter, mocked_session: Any) -> None:
    with client().trace.session() as call:
        assert "efficientai.channel" not in call.attributes


def test_chat_helpers_are_noops_when_disabled(spans: InMemorySpanExporter) -> None:
    call = api.CallTrace(call_short_id=None, enabled=False, channel="chat")
    call.user_message("hi")
    call.assistant_message("hello")
    with call.tool("x") as tool, call.retrieval() as kb:
        tool.set_result("r")
        kb.set_documents(1)
    assert spans.get_finished_spans() == ()
