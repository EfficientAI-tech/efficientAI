"""Offline request and response checks for the Anthropic LLM service."""

import copy
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from anthropic.types import Message, RawMessageStreamEvent
from pydantic import TypeAdapter

from efficientai.processors.aggregators.llm_context import LLMContext
from efficientai.services.anthropic.llm import AnthropicLLMContext, AnthropicLLMService


@pytest.fixture
def anthropic_service(monkeypatch):
    def block_network(*args, **kwargs):
        raise AssertionError("Network access is forbidden in Anthropic service tests")

    monkeypatch.setattr(socket, "getaddrinfo", block_network)
    monkeypatch.setattr(socket.socket, "connect", block_network)
    monkeypatch.setattr(socket.socket, "connect_ex", block_network)
    requests = []

    def make_service(content, **kwargs):
        async def handle(**body):
            requests.append(copy.deepcopy(body))
            message = {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": body["model"],
                "content": content,
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 5},
            }
            if not body["stream"]:
                return Message.model_validate(message)
            events = [
                {
                    "type": "message_start",
                    "message": {**message, "content": [], "stop_reason": None},
                },
                *content,
                {"type": "message_stop"},
            ]

            async def stream():
                for event in events:
                    yield TypeAdapter(RawMessageStreamEvent).validate_python(event)

            return stream()

        client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(side_effect=handle)))
        service = AnthropicLLMService(api_key="test-key", client=client, **kwargs)
        for method in ("push_frame", "push_error", "run_function_calls"):
            monkeypatch.setattr(service, method, AsyncMock())
        return service, requests

    return make_service


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
    assert not {"temperature", "top_p", "top_k", "thinking"} & requests[0].keys()


@pytest.mark.parametrize("model", ["claude-sonnet-5-5", "claude-haiku-4-5-20251001"])
@pytest.mark.parametrize("extra", [False, True])
async def test_stream_sampling_parameters(anthropic_service, model, extra):
    sampling = {"temperature": 0.7, "top_p": 0.9, "top_k": 10}
    params = AnthropicLLMService.InputParams(
        max_tokens=1234, **({"extra": sampling} if extra else sampling)
    )
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
