"""Streaming (sentence-by-sentence) replies for the ElevenLabs test agent."""

from __future__ import annotations

import asyncio
import time
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import importlib

llm_module = importlib.import_module("app.services.ai.llm_service")
from app.services.webrtc_bridge.test_agent_processor import (
    TestAgentConfig,
    TestAgentProcessor,
    _split_ready_segments,
)


def _processor() -> TestAgentProcessor:
    return TestAgentProcessor(
        TestAgentConfig(
            organization_id=uuid.uuid4(),
            db=MagicMock(),
            llm_provider="fireworks",
            llm_model="glm-5p3",
            response_delay_ms=0,
        )
    )


def _fake_llm(deltas, delay=0.0, final_text=None):
    def call(self, messages, *, on_text_delta=None, **kwargs):
        for d in deltas:
            if delay:
                time.sleep(delay)
            if on_text_delta:
                on_text_delta(d)
        return {"text": final_text if final_text is not None else "".join(deltas)}

    return call


async def _fake_tts(self, text):
    await asyncio.sleep(0.01)
    return text.encode()


def _segments(buffer: str) -> list[str]:
    return [seg.strip() for seg, _ in _split_ready_segments(buffer)]


def test_split_matches_pipecat_sentence_detection():
    assert _segments("Sure, my name is Shubh. And the email") == ["Sure, my name is Shubh."]
    assert _segments("Hi. Yes I'm") == ["Hi."]
    assert _segments("Thanks Dr. Shah for calling") == []
    assert _segments("Wait; then") == []  # matches pipecat: no split on ';'


def test_split_waits_for_text_after_boundary():
    # "3." might still become "3.5"; the stream end flushes the remainder.
    assert _segments("It costs 3.") == []
    assert _segments("It costs 3.5 rupees. Ok") == ["It costs 3.5 rupees."]


def test_split_cuts_run_on_text():
    run_on = "word, " * 60
    segments = _segments(run_on)
    assert segments and all(len(seg) <= 220 for seg in segments)


@pytest.mark.asyncio
async def test_first_sentence_is_spoken_before_llm_finishes():
    processor = _processor()
    spoken: list[tuple[float, bytes]] = []
    start = time.monotonic()

    async def speak(audio: bytes) -> int:
        spoken.append((time.monotonic() - start, audio))
        return len(audio)

    deltas = ["Sure, my name ", "is Shubh. ", "The email is ", "shubh@example.com."]
    with patch.object(TestAgentProcessor, "_sync_llm_call", _fake_llm(deltas, delay=0.15)), patch.object(
        TestAgentProcessor, "_text_to_speech", _fake_tts
    ):
        reply = await processor.process_agent_transcript_streaming("Your name?", speak)

    assert reply == "Sure, my name is Shubh. The email is shubh@example.com."
    assert [a for _, a in spoken] == [b"Sure, my name is Shubh.", b"The email is shubh@example.com."]
    # First segment went out while the LLM was still producing deltas (~0.6 s total).
    assert spoken[0][0] < 0.45
    assert processor.conversation_history[-1] == {"role": "assistant", "content": reply}


@pytest.mark.asyncio
async def test_barge_in_stops_reply_and_trims_history():
    processor = _processor()
    cancel = asyncio.Event()
    spoken: list[bytes] = []

    async def speak(audio: bytes) -> int:
        spoken.append(audio)
        cancel.set()  # agent starts talking during the first sentence
        return len(audio) // 2

    deltas = ["First sentence is here. ", "Second sentence never plays."]
    with patch.object(TestAgentProcessor, "_sync_llm_call", _fake_llm(deltas)), patch.object(
        TestAgentProcessor, "_text_to_speech", _fake_tts
    ):
        await processor.process_agent_transcript_streaming("Hi", speak, cancel_event=cancel)

    assert spoken == [b"First sentence is here."]
    last = processor.conversation_history[-1]["content"]
    assert last.endswith("[interrupted]")
    assert "Second sentence" not in last
    assert not processor.is_processing


@pytest.mark.asyncio
async def test_empty_stream_falls_back_to_non_streaming_retry():
    processor = _processor()
    spoken: list[bytes] = []

    async def speak(audio: bytes) -> int:
        spoken.append(audio)
        return len(audio)

    async def fallback(self, messages):
        return "Fallback reply here."

    with patch.object(TestAgentProcessor, "_sync_llm_call", _fake_llm([], final_text="")), patch.object(
        TestAgentProcessor, "_generate_via_llm_service", fallback
    ), patch.object(TestAgentProcessor, "_text_to_speech", _fake_tts):
        reply = await processor.process_agent_transcript_streaming("Hi", speak)

    assert reply == "Fallback reply here."
    assert spoken == [b"Fallback reply here."]


@pytest.mark.asyncio
async def test_cancel_before_any_audio_drops_reply():
    processor = _processor()
    cancel = asyncio.Event()
    cancel.set()
    spoken: list[bytes] = []

    async def speak(audio: bytes) -> int:
        spoken.append(audio)
        return len(audio)

    with patch.object(TestAgentProcessor, "_sync_llm_call", _fake_llm(["Never spoken at all."])), patch.object(
        TestAgentProcessor, "_text_to_speech", _fake_tts
    ):
        await processor.process_agent_transcript_streaming("Hi", speak, cancel_event=cancel)

    assert spoken == []


def test_llm_service_stream_completion_forwards_text_deltas():
    def chunk(content):
        return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content))])

    chunks = [chunk("Hel"), chunk(None), chunk("lo")]
    seen: list[str] = []
    with patch.object(llm_module.litellm, "completion", return_value=iter(chunks)) as completion, patch.object(
        llm_module.litellm, "stream_chunk_builder", return_value="rebuilt"
    ) as builder:
        result = llm_module._stream_completion({"model": "m"}, [{"role": "user", "content": "x"}], seen.append)

    assert seen == ["Hel", "lo"]
    assert result == "rebuilt"
    assert completion.call_args.kwargs["stream"] is True
    assert builder.call_args.args[0] == chunks


@pytest.mark.asyncio
async def test_non_streaming_result_is_used_without_second_llm_call():
    """A provider path that returns text without deltas (OpenRouter Jev) is not re-called."""
    processor = _processor()
    spoken: list[bytes] = []

    async def speak(audio: bytes) -> int:
        spoken.append(audio)
        return len(audio)

    async def must_not_call(self, messages):
        raise AssertionError("LLM called twice")

    with patch.object(TestAgentProcessor, "_sync_llm_call", _fake_llm([], final_text="Whole reply here.")), patch.object(
        TestAgentProcessor, "_generate_via_llm_service", must_not_call
    ), patch.object(TestAgentProcessor, "_text_to_speech", _fake_tts):
        reply = await processor.process_agent_transcript_streaming("Hi", speak)

    assert reply == "Whole reply here."
    assert spoken == [b"Whole reply here."]
