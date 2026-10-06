"""Barge-in support in TestAgentProcessor: early-stopping outbound audio."""

from __future__ import annotations

import asyncio

import pytest

from app.services.webrtc_bridge.test_agent_processor import TestAgentConfig, TestAgentProcessor


def _processor() -> TestAgentProcessor:
    return TestAgentProcessor(TestAgentConfig(sample_rate=16_000))


@pytest.mark.asyncio
async def test_stream_audio_chunks_sends_everything_without_cancel():
    processor = _processor()
    sent: list[bytes] = []

    async def cb(chunk: bytes) -> None:
        sent.append(chunk)

    audio = b"\x00" * 640 * 5  # 5 x 20 ms
    total = await processor.stream_audio_chunks(audio, cb, chunk_duration_ms=20)

    assert total == len(audio)
    assert len(sent) == 5


@pytest.mark.asyncio
async def test_stream_audio_chunks_stops_when_cancelled():
    processor = _processor()
    cancel = asyncio.Event()
    sent: list[bytes] = []

    async def cb(chunk: bytes) -> None:
        sent.append(chunk)
        if len(sent) == 3:
            cancel.set()

    audio = b"\x00" * 640 * 10
    total = await processor.stream_audio_chunks(
        audio, cb, chunk_duration_ms=20, cancel_event=cancel
    )

    assert len(sent) == 3
    assert total == 640 * 3


def test_mark_last_response_interrupted_truncates_history():
    processor = _processor()
    processor.conversation_history = [
        {"role": "user", "content": "How can I help?"},
        {"role": "assistant", "content": "one two three four five six seven eight nine ten"},
    ]

    processor.mark_last_response_interrupted(0.3)

    assert processor.conversation_history[-1]["content"] == "one two three — [interrupted]"


def test_mark_last_response_interrupted_before_speaking():
    processor = _processor()
    processor.conversation_history = [{"role": "assistant", "content": "hello there"}]

    processor.mark_last_response_interrupted(0.0)

    assert processor.conversation_history[-1]["content"] == "[interrupted before speaking]"
