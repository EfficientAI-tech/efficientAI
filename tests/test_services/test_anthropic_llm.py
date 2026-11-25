"""Offline request and tool round-trip checks using the real Anthropic SDK."""

import asyncio
import copy
import json
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx2
import pytest
from anthropic import AsyncAnthropic, AsyncAnthropicBedrock, AsyncAnthropicVertex

from efficientai.adapters.services.open_ai_adapter import OpenAILLMAdapter
from efficientai.frames.frames import (
    InterruptionFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    ManuallySwitchServiceFrame,
    TextFrame,
)
from efficientai.pipeline.llm_switcher import LLMSwitcher
from efficientai.pipeline.service_switcher import ServiceSwitcherStrategyManual
from efficientai.processors.aggregators.llm_context import LLMContext
from efficientai.processors.aggregators.llm_response_universal import LLMAssistantAggregator
from efficientai.processors.aggregators.openai_llm_context import OpenAILLMContextFrame
from efficientai.processors.frame_processor import FrameDirection
from efficientai.services.anthropic.llm import (
    AnthropicAssistantContextAggregator,
    AnthropicLLMContext,
    AnthropicLLMService,
)
from efficientai.services.llm_service import LLMService
from efficientai.services.openai.llm import OpenAILLMService


def message_events(message):
    """Encode the documented SSE sequence, including omitted and redacted thinking."""
    yield {
        "type": "message_start",
        "message": {
            **message,
            "content": [],
            "stop_reason": None,
            "usage": {"input_tokens": message["usage"]["input_tokens"], "output_tokens": 1},
        },
    }
    for index, block in enumerate(message["content"]):
        start = copy.deepcopy(block)
        deltas = []
        if block["type"] == "text":
            start["text"] = ""
            deltas = [{"type": "text_delta", "text": block["text"]}]
        elif block["type"] == "thinking":
            start.update(thinking="", signature="")
            deltas = [
                {"type": "thinking_delta", "thinking": block["thinking"]},
                {"type": "signature_delta", "signature": block["signature"]},
            ]
        elif block["type"] == "tool_use":
            start["input"] = {}
            encoded = json.dumps(block["input"])
            split = len(encoded) // 2
            deltas = [
                {"type": "input_json_delta", "partial_json": encoded[:split]},
                {"type": "input_json_delta", "partial_json": encoded[split:]},
            ]
        yield {"type": "content_block_start", "index": index, "content_block": start}
        for delta in deltas:
            yield {"type": "content_block_delta", "index": index, "delta": delta}
        yield {"type": "content_block_stop", "index": index}
    yield {
        "type": "message_delta",
        "delta": {"stop_reason": message["stop_reason"], "stop_sequence": None},
        "usage": {"output_tokens": 5},
    }
    yield {
        "type": "message_delta",
        "delta": {"stop_reason": message["stop_reason"], "stop_sequence": None},
        "usage": {"output_tokens": 12},
    }
    yield {"type": "message_stop"}


@pytest.fixture
async def anthropic_service(monkeypatch):
    def block_network(*args, **kwargs):
        raise AssertionError("Network access is forbidden in Anthropic service tests")

    monkeypatch.setattr(socket, "getaddrinfo", block_network)
    monkeypatch.setattr(socket.socket, "connect", block_network)
    monkeypatch.setattr(socket.socket, "connect_ex", block_network)
    clients = []

    def make_service(
        content,
        *,
        stop_reason="end_turn",
        events=None,
        stream_error=None,
        input_tokens=10,
        api_version=None,
        **kwargs,
    ):
        requests = []

        def handle(request):
            body = json.loads(request.content)
            requests.append(body)
            if (
                request.headers["anthropic-version"] >= "2026-10-21"
                or body["model"] == "claude-sonnet-5-5"
            ) and {"temperature", "top_p", "top_k"} & body.keys():
                return httpx2.Response(
                    400,
                    json={
                        "type": "error",
                        "error": {"type": "invalid_request_error", "message": "Sampling removed"},
                    },
                )
            message = {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": body["model"],
                "content": content,
                "stop_reason": stop_reason,
                "stop_sequence": None,
                "usage": {"input_tokens": input_tokens, "output_tokens": 12},
            }
            if not body["stream"]:
                return httpx2.Response(200, json=message)
            stream_events = events if events is not None else message_events(message)
            payload = "".join(
                f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in stream_events
            )

            class ResponseStream(httpx2.AsyncByteStream):
                async def __aiter__(self):
                    yield payload.encode()
                    if stream_error:
                        raise stream_error

            return httpx2.Response(
                200, stream=ResponseStream(), headers={"content-type": "text/event-stream"}
            )

        client = AsyncAnthropic(
            api_key="test-key",
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle)),
            max_retries=0,
            default_headers={"anthropic-version": api_version} if api_version else None,
        )
        clients.append(client)
        service = AnthropicLLMService(api_key="test-key", client=client, **kwargs)
        for method in ("push_frame", "push_error", "run_function_calls", "_report_usage_metrics"):
            monkeypatch.setattr(service, method, AsyncMock())
        return service, requests

    yield make_service
    for client in clients:
        await client.close()


@pytest.fixture
def connect_assistant(monkeypatch):
    def connect(service, context):
        assistant = (
            LLMAssistantAggregator(context)
            if isinstance(context, LLMContext)
            else AnthropicAssistantContextAggregator(context)
        )
        monkeypatch.setattr(assistant, "push_frame", AsyncMock())

        async def relay(frame, direction=FrameDirection.DOWNSTREAM):
            if direction == FrameDirection.DOWNSTREAM:
                await assistant.process_frame(frame, direction)

        async def broadcast(frame_class, **kwargs):
            await relay(frame_class(**kwargs))

        async def cancel_task(task):
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        monkeypatch.setattr(service, "push_frame", relay)
        monkeypatch.setattr(service, "broadcast_frame", broadcast)
        monkeypatch.setattr(service, "create_task", asyncio.create_task)
        monkeypatch.setattr(service, "cancel_task", cancel_task)
        monkeypatch.setattr(
            service, "run_function_calls", LLMService.run_function_calls.__get__(service)
        )
        return assistant

    return connect


@pytest.mark.parametrize("context_class", [LLMContext, AnthropicLLMContext])
async def test_inference_reads_text_after_thinking(anthropic_service, context_class):
    service, requests = anthropic_service(
        [
            {"type": "thinking", "thinking": "", "signature": "signed-thinking"},
            {"type": "text", "text": "hello "},
            {"type": "text", "text": "world"},
        ]
    )

    result = await service.run_inference(context_class([{"role": "user", "content": "hi"}]))

    assert result == "hello world"
    assert requests[0]["model"] == "claude-sonnet-5-5"
    assert requests[0]["max_tokens"] == 8192
    assert requests[0]["output_config"] == {"effort": "high"}
    assert not {"temperature", "top_p", "top_k", "thinking"} & requests[0].keys()


@pytest.mark.parametrize("content", [[], [{"type": "redacted_thinking", "data": "opaque"}]])
async def test_inference_without_text(anthropic_service, content):
    service, _ = anthropic_service(content)
    assert await service.run_inference(LLMContext([{"role": "user", "content": "hi"}])) == ""


@pytest.mark.parametrize(
    "model", ["claude-sonnet-5-5", "claude-haiku-4-5-20251001", "claude-sonnet-4-5-20250929"]
)
@pytest.mark.parametrize("source", ["fields", "extra", "extra_body"])
@pytest.mark.parametrize("api_version", ["2023-06-01", "2026-10-21"])
async def test_stream_sampling_parameters(anthropic_service, model, source, api_version):
    sampling = {"temperature": 0.7, "top_p": 0.9, "top_k": 10}
    settings = sampling if source == "fields" else {"extra": sampling}
    if source == "extra_body":
        settings = {"extra": {"extra_body": sampling}}
    params = AnthropicLLMService.InputParams(max_tokens=1234, **settings)
    original = copy.deepcopy(params.extra)
    service, requests = anthropic_service([], model=model, params=params, api_version=api_version)

    await service._process_context(LLMContext([{"role": "user", "content": "hi"}]))

    service.push_error.assert_not_called()
    assert requests[0]["model"] == model
    assert requests[0]["max_tokens"] == 1234
    assert requests[0]["stream"] is True
    for key, value in sampling.items():
        if model == "claude-sonnet-5-5" or api_version >= "2026-10-21":
            assert key not in requests[0]
        else:
            assert requests[0][key] == value
    assert params.extra == original


@pytest.mark.parametrize("override_source", ["model", "extra_body"])
async def test_model_overrides_apply_restrictions(anthropic_service, override_source):
    override = {"model": "claude-sonnet-5-5", "temperature": 0.7}
    extra = override if override_source == "model" else {"extra_body": override}
    service, requests = anthropic_service(
        [], model="claude-haiku-4-5-20251001", params=AnthropicLLMService.InputParams(extra=extra)
    )
    await service._process_context(LLMContext([{"role": "user", "content": "hi"}]))
    service.push_error.assert_not_called()
    assert requests[0]["model"] == "claude-sonnet-5-5"
    assert "temperature" not in requests[0]
    assert requests[0]["output_config"]["effort"] == "high"


async def test_effort_and_output_format_override(anthropic_service):
    service, requests = anthropic_service(
        [],
        params=AnthropicLLMService.InputParams(
            extra={
                "output_config": {"effort": "medium"},
                "extra_body": {
                    "output_config": {
                        "format": {
                            "type": "json_schema",
                            "schema": {
                                "type": "object",
                                "properties": {},
                                "additionalProperties": False,
                            },
                        }
                    }
                },
            }
        ),
    )
    await service._process_context(LLMContext([{"role": "user", "content": "hi"}]))
    service.push_error.assert_not_called()
    assert requests[0]["output_config"] == {
        "effort": "medium",
        "format": {
            "type": "json_schema",
            "schema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    }


@pytest.mark.parametrize(
    "extra, message",
    [
        ({"thinking": {"type": "disabled"}}, "thinking.type"),
        ({"thinking": {"type": "enabled", "budget_tokens": 1024}}, "thinking.type"),
        ({"thinking": {"type": "adaptive", "budget_tokens": 1024}}, "budget_tokens"),
        ({"thinking": {"type": "between_tools", "display": "omitted"}}, "between_tools"),
        (
            {"thinking": {"type": "between_tools"}, "output_config": {"effort": "max"}},
            "between_tools",
        ),
        ({"tool_choice": {"type": "any"}}, "tool_choice"),
        ({"extra_body": {"tool_choice": {"type": "tool", "name": "search"}}}, "tool_choice"),
    ],
)
async def test_unsupported_settings_fail_before_request(anthropic_service, extra, message):
    service, requests = anthropic_service([], params=AnthropicLLMService.InputParams(extra=extra))
    await service._process_context(LLMContext([{"role": "user", "content": "hi"}]))
    assert requests == []
    assert message in service.push_error.call_args.args[0].error


async def test_assistant_prefill_fails_before_request(anthropic_service):
    service, requests = anthropic_service([])
    with pytest.raises(ValueError, match="prefill"):
        await service.run_inference(LLMContext([{"role": "assistant", "content": "answer:"}]))
    assert requests == []


@pytest.mark.parametrize("context_class", [LLMContext, AnthropicLLMContext])
@pytest.mark.parametrize("thinking", ["", "a summary"])
async def test_tool_round_trip_preserves_complete_response(
    anthropic_service, connect_assistant, context_class, thinking
):
    content = [
        {"type": "thinking", "thinking": thinking, "signature": "signed-thinking"},
        {"type": "text", "text": "  Checking both cities.\n"},
        {"type": "redacted_thinking", "data": "opaque-data"},
        {"type": "tool_use", "id": "call_1", "name": "weather", "input": {"city": "Paris"}},
        {"type": "thinking", "thinking": "", "signature": "another-signature"},
        {"type": "tool_use", "id": "call_2", "name": "weather", "input": {"city": "東京"}},
    ]
    service, requests = anthropic_service(content, stop_reason="tool_use")
    context = context_class([{"role": "user", "content": "compare the weather"}])
    connect_assistant(service, context)

    async def weather(params):
        await params.result_callback({"city": params.arguments["city"], "temperature": 20})

    service.register_function("weather", weather)

    await service._process_context(context)
    await asyncio.gather(*list(service._function_call_tasks))
    service.push_error.assert_not_called()
    service._report_usage_metrics.assert_awaited_once_with(
        prompt_tokens=10,
        completion_tokens=12,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )

    # A second SDK request must echo the exact assistant message before both results.
    await service.run_inference(context)
    messages = requests[1]["messages"]
    assert len(messages) == 3
    assert messages[1] == {"role": "assistant", "content": content}
    assert messages[2]["role"] == "user"
    assert [block["tool_use_id"] for block in messages[2]["content"]] == ["call_1", "call_2"]
    assert all("IN_PROGRESS" not in block["content"] for block in messages[2]["content"])

    if context_class is LLMContext:
        messages = OpenAILLMAdapter().get_llm_invocation_params(context)["messages"]
        assert messages[1] == {
            "role": "assistant",
            "content": [{"type": "text", "text": "  Checking both cities.\n"}],
        }
        assert [call["id"] for call in messages[2]["tool_calls"]] == ["call_1", "call_2"]
        assert [
            json.loads(call["function"]["arguments"]) for call in messages[2]["tool_calls"]
        ] == [
            {"city": "Paris"},
            {"city": "東京"},
        ]
        assert [m["tool_call_id"] for m in messages[3:]] == ["call_1", "call_2"]
        assert all(m["role"] == "tool" and "temperature" in m["content"] for m in messages[3:])


async def test_switch_to_openai_keeps_replies_and_back_preserves_signature(
    anthropic_service, connect_assistant, monkeypatch
):
    content = [
        {"type": "thinking", "thinking": "", "signature": "signed-thinking"},
        {"type": "text", "text": "hello "},
        {"type": "text", "text": "world"},
    ]
    service, requests = anthropic_service(content)
    context = LLMContext([{"role": "user", "content": "hi"}])
    connect_assistant(service, context)
    await service._process_context(context)
    service.push_error.assert_not_called()
    context.add_message({"role": "user", "content": "continue"})

    openai = OpenAILLMService(api_key="test-key")
    create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="openai reply"))]
        )
    )
    monkeypatch.setattr(openai._client.chat.completions, "create", create)
    try:
        switcher = LLMSwitcher([service, openai], ServiceSwitcherStrategyManual)
        switcher.strategy.handle_frame(
            ManuallySwitchServiceFrame(service=openai), FrameDirection.DOWNSTREAM
        )
        assert await switcher.run_inference(context) == "openai reply"
        assert create.call_args.kwargs["messages"] == [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "hello "}, {"type": "text", "text": "world"}],
            },
            {"role": "user", "content": "continue"},
        ]
        context.add_message({"role": "assistant", "content": "openai reply"})
        context.add_message({"role": "user", "content": "back to Claude"})
        switcher.strategy.handle_frame(
            ManuallySwitchServiceFrame(service=service), FrameDirection.DOWNSTREAM
        )
        assert await switcher.run_inference(context) == "hello world"
        assert requests[1]["messages"][1] == {"role": "assistant", "content": content}
        assert len(requests[1]["messages"]) == 5
    finally:
        await openai._client.close()


@pytest.mark.parametrize("context_class", [LLMContext, AnthropicLLMContext])
@pytest.mark.parametrize("outcome", ["complete", "interrupt", "stop", "error"])
async def test_sequential_tools_have_results_while_queued_and_when_stopped(
    anthropic_service, connect_assistant, context_class, outcome
):
    content = [
        {"type": "thinking", "thinking": "", "signature": "signed"},
        {"type": "tool_use", "id": "call_1", "name": "work", "input": {}},
        {"type": "tool_use", "id": "call_2", "name": "work", "input": {}},
    ]
    service, requests = anthropic_service(content, stop_reason="tool_use", run_in_parallel=False)
    context = context_class([{"role": "user", "content": "do both"}])
    assistant = connect_assistant(service, context)
    started = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()
    executed = []

    async def work(params):
        executed.append(params.tool_call_id)
        if params.tool_call_id == "call_1":
            started.set()
            await release.wait()
            if outcome == "error":
                raise ValueError("tool failed")
        await params.result_callback({"done": params.tool_call_id})
        if params.tool_call_id == "call_2":
            finished.set()

    # Shutdown must resolve placeholders even for tools protected from interruptions.
    service.register_function("work", work, cancel_on_interruption=outcome != "stop")
    await service._create_sequential_runner_task()
    try:
        await service._process_context(context)
        await asyncio.wait_for(started.wait(), timeout=2)
        assert executed == ["call_1"]
        # A new user turn arrives while the second call is still queued.
        context.add_message({"role": "user", "content": "status?"})
        await service.run_inference(context)
        messages = requests[1]["messages"]
        assert messages[1] == {"role": "assistant", "content": content}
        results = [b for b in messages[2]["content"] if b["type"] == "tool_result"]
        assert [b["tool_use_id"] for b in results] == ["call_1", "call_2"]
        assert [b["content"] for b in results] == ["IN_PROGRESS", "IN_PROGRESS"]

        if outcome == "interrupt":
            await service._handle_interruptions(InterruptionFrame())
            assert not service._sequential_runner_task.done()
        elif outcome == "stop":
            await service._cancel_sequential_runner_task()
        else:
            release.set()
            await asyncio.wait_for(finished.wait(), timeout=2)

        await service.run_inference(context)
        results = [b for b in requests[2]["messages"][2]["content"] if b["type"] == "tool_result"]
        assert [b["tool_use_id"] for b in results] == ["call_1", "call_2"]
        expected = (
            ["CANCELLED", "CANCELLED"]
            if outcome in ("interrupt", "stop")
            else [
                "CANCELLED" if outcome == "error" else json.dumps({"done": "call_1"}),
                json.dumps({"done": "call_2"}),
            ]
        )
        assert [b["content"] for b in results] == expected
        assert not assistant.has_function_calls_in_progress
        assert service._sequential_runner_queue.empty()
        assert executed == (
            ["call_1"] if outcome in ("interrupt", "stop") else ["call_1", "call_2"]
        )
        if outcome == "error":
            assert "tool failed" in service.push_error.call_args.args[0].error
        else:
            service.push_error.assert_not_called()
    finally:
        await service._cancel_sequential_runner_task()


@pytest.mark.parametrize("context_class", [LLMContext, AnthropicLLMContext])
@pytest.mark.parametrize("handler_name", ["work", None])
async def test_interruption_keeps_protected_queued_tools_running(
    anthropic_service, connect_assistant, context_class, handler_name
):
    content = [
        {"type": "tool_use", "id": "call_1", "name": "work", "input": {}},
        {"type": "tool_use", "id": "call_2", "name": "work", "input": {}},
        {"type": "tool_use", "id": "call_3", "name": "keep", "input": {}},
    ]
    service, requests = anthropic_service(content, stop_reason="tool_use", run_in_parallel=False)
    context = context_class([{"role": "user", "content": "do all three"}])
    assistant = connect_assistant(service, context)
    started = asyncio.Event()
    finished = asyncio.Event()
    executed = []

    async def work(params):
        executed.append(params.tool_call_id)
        started.set()
        await asyncio.Event().wait()

    async def keep(params):
        executed.append(params.tool_call_id)
        await params.result_callback({"done": True})
        finished.set()

    service.register_function(handler_name, work)
    service.register_function("keep", keep, cancel_on_interruption=False)
    await service._create_sequential_runner_task()
    try:
        await service._process_context(context)
        await asyncio.wait_for(started.wait(), timeout=2)
        await service._handle_interruptions(InterruptionFrame())
        await asyncio.wait_for(finished.wait(), timeout=2)
        await service.run_inference(context)
        results = requests[1]["messages"][2]["content"]
        assert [b["tool_use_id"] for b in results] == ["call_1", "call_2", "call_3"]
        assert [b["content"] for b in results] == ["CANCELLED", "CANCELLED", '{"done": true}']
        assert executed == ["call_1", "call_3"]
        assert not assistant.has_function_calls_in_progress
        assert not service._sequential_runner_task.done()
        service.push_error.assert_not_called()
    finally:
        await service._cancel_sequential_runner_task()


@pytest.mark.parametrize("context_class", [LLMContext, AnthropicLLMContext])
async def test_all_results_exist_before_reporting_missing_handler(
    anthropic_service, monkeypatch, context_class
):
    content = [
        {"type": "tool_use", "id": "call_1", "name": "missing", "input": {}},
        {"type": "tool_use", "id": "call_2", "name": "work", "input": {}},
    ]
    service, _ = anthropic_service(content, stop_reason="tool_use")
    service.register_function("work", AsyncMock())
    context = context_class([{"role": "user", "content": "do both"}])

    async def check_results(_):
        messages = service._get_llm_invocation_params(context)["messages"]
        assert messages[1] == {"role": "assistant", "content": content}
        results = messages[2]["content"]
        assert [b["tool_use_id"] for b in results] == ["call_1", "call_2"]
        assert results[0]["is_error"] is True
        assert results[1]["content"] == "IN_PROGRESS"

    push_error = AsyncMock(side_effect=check_results)
    monkeypatch.setattr(service, "push_error", push_error)
    await service._process_context(context)
    push_error.assert_awaited_once()


@pytest.mark.parametrize("context_class", [LLMContext, AnthropicLLMContext])
async def test_aggregator_defaults_still_append_text(monkeypatch, context_class):
    context = context_class([{"role": "user", "content": "hi"}])
    assistant = (
        LLMAssistantAggregator(context)
        if context_class is LLMContext
        else AnthropicAssistantContextAggregator(context)
    )
    monkeypatch.setattr(assistant, "push_frame", AsyncMock())
    for append in (False, True):
        await assistant.process_frame(
            LLMFullResponseStartFrame(append_to_context=append), FrameDirection.DOWNSTREAM
        )
        await assistant.process_frame(TextFrame("hello"), FrameDirection.DOWNSTREAM)
        await assistant.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)
    assert context.get_messages()[-1] == {"role": "assistant", "content": "hello"}
    assert len(context.get_messages()) == 2
    context_frames = [
        call.args[0]
        for call in assistant.push_frame.call_args_list
        if isinstance(call.args[0], (LLMContextFrame, OpenAILLMContextFrame))
    ]
    assert len(context_frames) == 2


@pytest.mark.parametrize("context_class", [LLMContext, AnthropicLLMContext])
@pytest.mark.parametrize("stop_reason", ["max_tokens", "refusal"])
async def test_partial_or_refused_tool_is_not_executed(
    anthropic_service, stop_reason, context_class
):
    service, _ = anthropic_service(
        [{"type": "tool_use", "id": "call_1", "name": "search", "input": {}}],
        stop_reason=stop_reason,
    )
    context = context_class([{"role": "user", "content": "hi"}])
    await service._process_context(context)
    assert stop_reason in service.push_error.call_args.args[0].error
    service.run_function_calls.assert_not_called()
    assert len(context.get_messages()) == 1


@pytest.mark.parametrize(
    "encoded, block_stopped",
    [("not JSON", True), ('{"q": "unfinished"', True), ('["not an object"]', True), ("{}", False)],
)
async def test_malformed_stream_does_not_commit_partial_response(
    anthropic_service, encoded, block_stopped
):
    events = [
        {
            "type": "message_start",
            "message": {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-5-5",
                "content": [],
                "usage": {"input_tokens": 1, "output_tokens": 0},
            },
        },
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "tool_use", "id": "call_1", "name": "search", "input": {}},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": encoded},
        },
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use", "stop_sequence": None},
            "usage": {"output_tokens": 5},
        },
        {
            "type": "message_stop",
        },
    ]
    if not block_stopped:
        events = [event for event in events if event["type"] != "content_block_stop"]
    service, _ = anthropic_service([], events=events)
    context = LLMContext([{"role": "user", "content": "hi"}])
    await service._process_context(context)
    service.push_error.assert_awaited_once()
    service.run_function_calls.assert_not_called()
    assert len(context.get_messages()) == 1


@pytest.mark.parametrize("model", ["anthropic.claude-sonnet-5-5", "us.anthropic.claude-sonnet-5-5"])
async def test_custom_platform_model_id_is_preserved(anthropic_service, model):
    service, requests = anthropic_service(
        [], model=model, params=AnthropicLLMService.InputParams(temperature=0.7)
    )
    await service._process_context(LLMContext([{"role": "user", "content": "hi"}]))
    service.push_error.assert_not_called()
    assert requests[0]["model"] == model
    assert "temperature" not in requests[0]


@pytest.mark.parametrize("thinking", [{"type": "adaptive"}, {"type": "between_tools"}])
async def test_supported_thinking_settings(anthropic_service, thinking):
    service, requests = anthropic_service(
        [], params=AnthropicLLMService.InputParams(extra={"thinking": thinking})
    )
    await service._process_context(LLMContext([{"role": "user", "content": "hi"}]))
    service.push_error.assert_not_called()
    assert requests[0]["thinking"] == thinking


@pytest.mark.parametrize("stream_error", [None, asyncio.CancelledError()])
async def test_incomplete_stream_is_not_stored_and_connection_closes(
    anthropic_service, monkeypatch, stream_error
):
    # A well-formed prefix without message_stop is still an incomplete response.
    message = {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5-5",
        "content": [{"type": "thinking", "thinking": "", "signature": ""}],
        "usage": {"input_tokens": 10, "output_tokens": 1},
        "stop_reason": "end_turn",
    }
    events = list(message_events(message))[:-3]
    service, _ = anthropic_service([], events=events, stream_error=stream_error)
    context = LLMContext([{"role": "user", "content": "hi"}])
    streams = []
    original = service._create_message_stream

    async def capture_stream(*args):
        stream = await original(*args)
        streams.append(stream)
        return stream

    monkeypatch.setattr(service, "_create_message_stream", capture_stream)
    if stream_error:
        with pytest.raises(asyncio.CancelledError):
            await service._process_context(context)
        service.push_error.assert_not_called()
    else:
        await service._process_context(context)
        assert "message_stop" in service.push_error.call_args.args[0].error
    assert len(context.get_messages()) == 1
    assert streams[0].response.is_closed
    service.run_function_calls.assert_not_called()


async def test_older_model_still_dispatches_every_tool(anthropic_service):
    content = [
        {"type": "tool_use", "id": "call_1", "name": "search", "input": {"q": "first"}},
        {"type": "tool_use", "id": "call_2", "name": "search", "input": {"q": "second"}},
    ]
    service, _ = anthropic_service(
        content, stop_reason="tool_use", model="claude-haiku-4-5-20251001"
    )
    await service._process_context(LLMContext([{"role": "user", "content": "hi"}]))
    service.push_error.assert_not_called()
    calls = service.run_function_calls.call_args.args[0]
    assert [call.tool_call_id for call in calls] == ["call_1", "call_2"]
    assert all(call.append_to_context for call in calls)


@pytest.mark.parametrize("context_class", [LLMContext, AnthropicLLMContext])
async def test_unregistered_tool_leaves_valid_history(anthropic_service, context_class):
    content = [
        {"type": "thinking", "thinking": "", "signature": "signed"},
        {"type": "tool_use", "id": "missing", "name": "missing_handler", "input": {}},
    ]
    service, requests = anthropic_service(content, stop_reason="tool_use")
    context = context_class([{"role": "user", "content": "hi"}])
    await service._process_context(context)
    assert "No handler registered" in service.push_error.call_args.args[0].error
    await service.run_inference(context)
    assert requests[1]["messages"][1] == {"role": "assistant", "content": content}
    result = requests[1]["messages"][2]["content"][0]
    assert result["type"] == "tool_result"
    assert result["tool_use_id"] == "missing"
    assert result["is_error"] is True
    if context_class is LLMContext:
        messages = OpenAILLMAdapter().get_llm_invocation_params(context)["messages"]
        assert messages[1]["tool_calls"][0]["id"] == "missing"
        assert messages[2] == {
            "role": "tool",
            "tool_call_id": "missing",
            "content": "No handler registered for tool 'missing_handler'.",
        }


async def test_stream_timeout_uses_completion_timeout_event(anthropic_service, monkeypatch):
    service, _ = anthropic_service([], stream_error=httpx2.ReadTimeout("timed out"))
    event_handler = AsyncMock()
    monkeypatch.setattr(service, "_call_event_handler", event_handler)
    await service._process_context(LLMContext([{"role": "user", "content": "hi"}]))
    event_handler.assert_awaited_once_with("on_completion_timeout")
    service.push_error.assert_not_called()
    service.run_function_calls.assert_not_called()


@pytest.mark.parametrize(
    "model, expected", [("claude-sonnet-5-5", 1), ("claude-haiku-4-5-20251001", 0)]
)
async def test_legacy_context_cache_threshold(anthropic_service, model, expected):
    service, _ = anthropic_service([], model=model, input_tokens=600)
    context = AnthropicLLMContext([{"role": "user", "content": "hi"}])
    await service._process_context(context)
    service.push_error.assert_not_called()
    assert context.turns_above_cache_threshold == expected


@pytest.mark.parametrize("api_version", ["2023-06-01", "2026-10-21"])
async def test_request_api_version_overrides_client_version(anthropic_service, api_version):
    service, requests = anthropic_service(
        [],
        model="claude-haiku-4-5-20251001",
        api_version="2026-10-21" if api_version == "2023-06-01" else "2023-06-01",
        params=AnthropicLLMService.InputParams(
            temperature=0.7,
            extra={"extra_headers": {"Anthropic-Version": api_version}},
        ),
    )
    await service._process_context(LLMContext([{"role": "user", "content": "hi"}]))
    service.push_error.assert_not_called()
    assert ("temperature" in requests[0]) == (api_version == "2023-06-01")


@pytest.mark.parametrize("platform", ["bedrock", "vertex"])
@pytest.mark.parametrize("api_version", [None, "2023-06-01", "2026-10-21"])
@pytest.mark.parametrize("sonnet_5_5", [False, True])
async def test_cloud_client_sampling_matches_wire_api_version(platform, api_version, sonnet_5_5):
    requests = []

    def handle(request):
        body = json.loads(request.content)
        requests.append(body)
        assert ("temperature" in body) == (
            not sonnet_5_5
            and body["anthropic_version"].removeprefix("bedrock-").removeprefix("vertex-")
            < "2026-10-21"
        )
        return httpx2.Response(
            200,
            json={
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": [{"type": "text", "text": "hello"}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    http_client = httpx2.AsyncClient(transport=httpx2.MockTransport(handle))
    if platform == "bedrock":
        model = (
            "anthropic.claude-sonnet-5-5"
            if sonnet_5_5
            else "anthropic.claude-haiku-4-5-20251001-v1:0"
        )
        client = AsyncAnthropicBedrock(
            aws_region="us-east-1",
            aws_access_key="test-access",
            aws_secret_key="test-secret",
            http_client=http_client,
            max_retries=0,
        )
        if api_version == "2023-06-01":
            api_version = "bedrock-2023-05-31"
    else:
        model = "claude-sonnet-5-5" if sonnet_5_5 else "claude-haiku-4-5@20251001"
        if api_version == "2023-06-01":
            api_version = "vertex-2023-10-16"
        client = AsyncAnthropicVertex(
            project_id="test-project",
            region="us-east5",
            access_token="test-token",
            http_client=http_client,
            max_retries=0,
        )
    async with client:
        service = AnthropicLLMService(api_key="test-key", client=client, model=model)
        params = service._prepare_request_params(
            {
                "model": model,
                "max_tokens": 32,
                "messages": [{"role": "user", "content": "hi"}],
                "temperature": 0.7,
                "extra_body": {"anthropic_version": api_version} if api_version else {},
            }
        )
        response = await client.messages.create(**params)
        assert response.content[0].text == "hello"
    assert len(requests) == 1
