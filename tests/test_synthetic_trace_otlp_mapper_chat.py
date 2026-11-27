"""Chat-agent traces: user message -> LLM / tools / retrieval -> reply."""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.services.synthetic_traces.otlp_mapper import (
    _is_chat_trace,
    annotate_spans_with_display_turn,
    derive_turns_from_spans,
)

MS = 1_000_000
_counter = 0


def span(
    name: str,
    start_ms: int,
    end_ms: int,
    *,
    parent: Optional[str] = None,
    op: Optional[str] = None,
    **attrs: Any,
) -> Dict[str, Any]:
    global _counter
    _counter += 1
    attributes = {"efficientai.call_short_id": "482931", **attrs}
    if op:
        attributes["gen_ai.operation.name"] = op
    return {
        "span_id": f"s{_counter:04d}",
        "parent_span_id": parent,
        "name": name,
        "start_time_unix_nano": start_ms * MS,
        "end_time_unix_nano": end_ms * MS,
        "attributes": attributes,
    }


def chat_turn(t0: int, user: str, final: str, *, with_tool: bool = True) -> list:
    turn = span("turn", t0, t0 + 2000, **{"turn.number": 1})
    tid = turn["span_id"]
    spans = [
        turn,
        span("user_message", t0, t0, parent=tid, op="user_message", message=user),
    ]
    if with_tool:
        spans += [
            span(
                "llm",
                t0 + 10,
                t0 + 400,
                parent=tid,
                op="chat",
                **{
                    "gen_ai.request.model": "gpt-4o",
                    "gen_ai.provider.name": "openai",
                    "metrics.ttfb": 0.21,
                },
            ),
            span(
                "execute_tool lookup_order",
                t0 + 410,
                t0 + 700,
                parent=tid,
                op="execute_tool",
                **{"gen_ai.tool.name": "lookup_order"},
            ),
            span(
                "retrieval",
                t0 + 710,
                t0 + 800,
                parent=tid,
                op="retrieval",
                **{"retrieval.source": "faq", "retrieval.documents.count": 3},
            ),
        ]
    spans.append(
        span(
            "llm",
            t0 + 810,
            t0 + 1500,
            parent=tid,
            op="chat",
            output=final,
            **{"gen_ai.request.model": "gpt-4o", "metrics.ttfb": 0.35},
        )
    )
    return spans


def test_tool_loop_is_one_turn_with_final_reply():
    spans = chat_turn(0, "Where is my order 1234?", "It ships tomorrow.")
    assert _is_chat_trace(spans)
    turns = derive_turns_from_spans(spans)
    assert len(turns) == 1
    turn = turns[0]
    assert turn["transcript"] == "User: Where is my order 1234?\nAssistant: It ships tomorrow."
    assert turn["llm_ttfb_ms"] == 210.0  # first LLM call: time to first token for the user
    assert turn["sut_response_latency_ms"] == 1500.0  # user message -> final reply
    extra = turn["extra"]
    assert extra["pipeline_mode"] == "chat"
    assert extra["llm_calls"] == 2
    assert extra["llm_model"] == "gpt-4o"
    assert extra["tool_calls"] == [{"name": "lookup_order", "latency_ms": 290.0}]
    assert extra["retrievals"] == [{"latency_ms": 90.0, "source": "faq", "documents": 3}]
    assert turn.get("stt_ttfb_ms") is None and turn.get("tts_ttfb_ms") is None


def test_multiple_turns_and_display_annotation():
    spans = chat_turn(0, "Hi there", "Hello! How can I help?", with_tool=False)
    spans += chat_turn(5000, "Cancel my subscription", "Done, it's cancelled.")
    turns = derive_turns_from_spans(spans)
    assert [t["turn_number"] for t in turns] == [1, 2]
    assert "Cancel my subscription" in turns[1]["transcript"]

    annotated = annotate_spans_with_display_turn(spans, precomputed_turns=turns)
    tool = next(s for s in annotated if s["name"].startswith("execute_tool"))
    assert tool["attributes"]["efficientai.display_turn_number"] == 2


def test_explicit_assistant_message_wins_over_llm_output():
    spans = chat_turn(0, "What's the refund policy?", "RAW LLM OUTPUT", with_tool=False)
    tid = spans[0]["span_id"]
    spans.append(
        span(
            "assistant_message",
            1600,
            1600,
            parent=tid,
            op="assistant_message",
            message="You can get a refund within 30 days.",
        )
    )
    turn = derive_turns_from_spans(spans)[0]
    assert turn["extra"]["assistant_text"] == "You can get a refund within 30 days."
    assert turn["sut_response_latency_ms"] == 1600.0


def test_without_turn_spans_user_messages_split_turns_and_opener_is_kept():
    spans = [
        span("llm", 0, 300, op="chat", output="Welcome! Ask me anything."),
        span("user_message", 1000, 1000, op="user_message", message="Do you ship abroad?"),
        span("llm", 1010, 1400, op="chat", output="Yes, to 40 countries."),
        span("user_message", 3000, 3000, op="user_message", message="How long does it take?"),
        span("llm", 3010, 3500, op="chat", output="Usually 5 to 7 days."),
    ]
    turns = derive_turns_from_spans(spans)
    assert [t["transcript"] for t in turns] == [
        "Assistant: Welcome! Ask me anything.",
        "User: Do you ship abroad?\nAssistant: Yes, to 40 countries.",
        "User: How long does it take?\nAssistant: Usually 5 to 7 days.",
    ]


def test_channel_attribute_marks_chat_even_without_user_message_spans():
    spans = [span("llm", 0, 100, op="chat", output="hi", **{"efficientai.channel": "chat"})]
    assert _is_chat_trace(spans)


def test_voice_traces_are_not_treated_as_chat():
    spans = [
        span("stt", 0, 100, op="stt", transcript="hello there"),
        span("llm", 110, 300, op="chat", output="Hi! How can I help?"),
        span("user_message", 0, 0, op="user_message", message="hello there"),
    ]
    assert not _is_chat_trace(spans)
    turns = derive_turns_from_spans(spans)
    assert all(t["extra"].get("pipeline_mode") != "chat" for t in turns)
