"""Contract: spans produced by efficientai-sdk are understood by the trace ingest mapper.

The SDK builds spans with its public tracing API, they are encoded exactly as the OTLP
HTTP exporter sends them, then parsed and projected onto turns by the server code.
If the span conventions drift on either side, this test fails.
"""

from __future__ import annotations

import asyncio

import pytest
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.services.synthetic_traces.otlp_ingest import parse_otlp_protobuf
from app.services.synthetic_traces.otlp_mapper import (
    derive_turns_from_spans,
    extract_correlation_ids,
    extract_pipeline_models,
    group_spans_by_call_short_id,
)
from efficientai_sdk import AsyncEfficientAI
from efficientai_sdk.tracing import otel as sdk_otel



@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> InMemorySpanExporter:
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    memory = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(memory))
    # Keep the SDK from exporting over the network during the test.
    monkeypatch.setattr(sdk_otel, "ensure_export_pipeline", lambda **_: True)
    return memory


def _handshake(call_short_id: str, run_id: str) -> dict:
    return {
        "type": "efficientai_trace_handshake",
        "call_short_id": call_short_id,
        "agent_id": "agent-1",
        "workspace_id": "ws-1",
        "transport": "websocket",
        "otel_correlation": {
            "otlp_endpoint": "http://localhost:8000/api/v1/observability/traces",
            "suggested_span_attributes": {"efficientai.evaluator_result_id": run_id},
        },
    }


CONVERSATIONS = {
    "alpha": [
        ("I would like to book a table for tonight", "Sure, how many people will be joining?"),
        ("Four of us, around eight", "Done. You're booked for four at 8pm."),
    ],
    "beta": [
        ("My internet keeps dropping every evening", "Sorry about that. Have you restarted the router?"),
        ("Yes, twice already today", "Thanks. I'm scheduling a technician visit for you."),
    ],
}


async def _run_call(client: AsyncEfficientAI, call_short_id: str, run_id: str, label: str):
    async with client.trace.session(handshake=_handshake(call_short_id, run_id)) as call:
        for user_text, agent_text in CONVERSATIONS[label]:
            with call.turn():
                with call.stt(model="nova-3", provider="deepgram") as stt:
                    stt.set_transcript(user_text)
                    await asyncio.sleep(0.002)
                with call.llm(model="gpt-4o", provider="openai") as llm:
                    llm.set_output(agent_text).set_ttfb(0.25)
                    await asyncio.sleep(0.002)
                with call.tts(model="sonic", provider="cartesia") as tts:
                    tts.set_text(agent_text).set_ttfb(0.12)
                    await asyncio.sleep(0.002)


@pytest.mark.asyncio
async def test_sdk_spans_map_to_turns_and_separate_concurrent_calls(captured):
    client = AsyncEfficientAI(api_key="key", workspace_id="ws-1")
    await asyncio.gather(
        _run_call(client, "111111", "run-a", "alpha"),
        _run_call(client, "222222", "run-b", "beta"),
    )
    await client.close()

    finished = [
        s
        for s in captured.get_finished_spans()
        if (s.attributes or {}).get("efficientai.call_short_id") in {"111111", "222222"}
    ]
    wire = encode_spans(finished).SerializeToString()
    parsed = parse_otlp_protobuf(wire)

    groups = group_spans_by_call_short_id(parsed, header_call_short_id=None)
    assert set(groups) == {"111111", "222222"}

    for call_id, label, run_id in (("111111", "alpha", "run-a"), ("222222", "beta", "run-b")):
        spans = groups[call_id]
        correlation = extract_correlation_ids(spans)
        assert correlation["evaluator_result_id"] == run_id
        assert correlation["agent_id"] == "agent-1"
        assert correlation["transport"] == "websocket"

        models = extract_pipeline_models(spans)
        assert models["llm"] == {"model": "gpt-4o", "provider": "openai"}
        assert models["stt"]["provider"] == "deepgram"
        assert models["tts"]["model"] == "sonic"

        turns = derive_turns_from_spans(spans)
        assert len(turns) == 2
        for turn, (user_text, agent_text) in zip(turns, CONVERSATIONS[label]):
            assert f"User: {user_text}" in turn["transcript"]
            assert f"Assistant: {agent_text}" in turn["transcript"]
            assert turn["llm_ttfb_ms"] == 250.0
            assert turn["tts_ttfb_ms"] == 120.0
            assert turn["sut_response_latency_ms"] is not None
