"""Offline request and tool round-trip checks using the real Anthropic SDK."""

import asyncio
import copy
import json
import socket
from unittest.mock import AsyncMock

import httpx2
import pytest
from anthropic import AsyncAnthropic

from efficientai.frames.frames import (
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    TextFrame,
)
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
        **kwargs,
    ):
        requests = []

        def handle(request):
            body = json.loads(request.content)
            requests.append(body)
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
        )
        clients.append(client)
        service = AnthropicLLMService(api_key="test-key", client=client, **kwargs)
        for method in ("push_frame", "push_error", "run_function_calls", "_report_usage_metrics"):
            monkeypatch.setattr(service, method, AsyncMock())
        return service, requests

    yield make_service
    for client in clients:
        await client.close()


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
async def test_stream_sampling_parameters(anthropic_service, model, source):
    sampling = {"temperature": 0.7, "top_p": 0.9, "top_k": 10}
    settings = sampling if source == "fields" else {"extra": sampling}
    if source == "extra_body":
        settings = {"extra": {"extra_body": sampling}}
    params = AnthropicLLMService.InputParams(max_tokens=1234, **settings)
    original = copy.deepcopy(params.extra)
    service, requests = anthropic_service([], model=model, params=params)

    await service._process_context(LLMContext([{"role": "user", "content": "hi"}]))

    service.push_error.assert_not_called()
    assert requests[0]["model"] == model
    assert requests[0]["max_tokens"] == 1234
    assert requests[0]["stream"] is True
    for key, value in sampling.items():
        if model == "claude-sonnet-5-5":
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
    anthropic_service, monkeypatch, context_class, thinking
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
    assistant = (
        LLMAssistantAggregator(context)
        if context_class is LLMContext
        else AnthropicAssistantContextAggregator(context)
    )
    monkeypatch.setattr(assistant, "push_frame", AsyncMock())

    async def relay(frame, direction=FrameDirection.DOWNSTREAM):
        if direction == FrameDirection.DOWNSTREAM:
            await assistant.process_frame(frame, direction)

    async def broadcast(frame_class, **kwargs):
        await relay(frame_class(**kwargs))

    async def weather(params):
        await params.result_callback({"city": params.arguments["city"], "temperature": 20})

    service.register_function("weather", weather)
    monkeypatch.setattr(service, "push_frame", relay)
    monkeypatch.setattr(service, "broadcast_frame", broadcast)
    monkeypatch.setattr(service, "create_task", asyncio.create_task)
    monkeypatch.setattr(
        service, "run_function_calls", LLMService.run_function_calls.__get__(service)
    )

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


@pytest.mark.parametrize("stop_reason", ["max_tokens", "refusal"])
async def test_partial_or_refused_tool_is_not_executed(anthropic_service, stop_reason):
    service, _ = anthropic_service(
        [{"type": "tool_use", "id": "call_1", "name": "search", "input": {}}],
        stop_reason=stop_reason,
    )
    await service._process_context(LLMContext([{"role": "user", "content": "hi"}]))
    service.push_error.assert_not_called()
    service.run_function_calls.assert_awaited_once_with([])


async def test_malformed_stream_does_not_commit_partial_response(anthropic_service):
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
            "delta": {"type": "input_json_delta", "partial_json": "not JSON"},
        },
    ]
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
