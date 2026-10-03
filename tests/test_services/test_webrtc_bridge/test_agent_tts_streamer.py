"""AgentTTSStreamer and streamed-TTS playback in the test agent."""

from __future__ import annotations

import asyncio
import time
import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.services.webrtc_bridge import agent_tts_streamer as streamer_module
from app.services.webrtc_bridge.agent_tts_streamer import AgentTTSStreamer
from app.services.webrtc_bridge.test_agent_processor import TestAgentConfig, TestAgentProcessor
from efficientai.frames.frames import (
    ErrorFrame,
    InterruptionFrame,
    TTSAudioRawFrame,
    TTSSpeakFrame,
    TTSStoppedFrame,
)
from efficientai.processors.frame_processor import FrameDirection, FrameProcessor


class FakeTTS(FrameProcessor):
    """Streams a few audio chunks per TTSSpeakFrame, like a websocket TTS."""

    def __init__(self, *, chunks=3, rate=16000, delay=0.02, fail=False, pause_after=None, pause_s=0.0):
        super().__init__()
        self._chunks, self._rate, self._delay, self._fail = chunks, rate, delay, fail
        self._pause_after, self._pause_s = pause_after, pause_s
        self._pause_frame_processing = True
        self.spoken: list[str] = []
        self.interruptions = 0

    async def process_frame(self, frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, TTSSpeakFrame):
            self.spoken.append(frame.text)
            if self._fail:
                await self.push_frame(ErrorFrame(error="tts socket closed"))
                return
            for i in range(self._chunks):
                await asyncio.sleep(self._delay)
                if self._pause_after is not None and i == self._pause_after:
                    await asyncio.sleep(self._pause_s)  # provider stalls mid-sentence
                await self.push_frame(TTSAudioRawFrame(b"\x01\x00" * 320, self._rate, 1))
            await self.push_frame(TTSStoppedFrame())
            return
        if isinstance(frame, InterruptionFrame):
            self.interruptions += 1
        await self.push_frame(frame, direction)


def _streamer(tts: FakeTTS, sample_rate=16000) -> AgentTTSStreamer:
    return AgentTTSStreamer(
        provider="sarvam", api_key="k", sample_rate=sample_rate, service_factory=lambda *a: tts
    )


async def _collect(streamer, text):
    return [chunk async for chunk in streamer.synthesize(text)]


@pytest.fixture(autouse=True)
def _fast_idle(monkeypatch):
    monkeypatch.setattr(streamer_module, "SEGMENT_IDLE_FALLBACK_S", 1.0)
    monkeypatch.setattr(streamer_module, "FIRST_AUDIO_TIMEOUT_S", 0.5)


@pytest.mark.asyncio
async def test_synthesize_streams_chunks_for_each_segment():
    tts = FakeTTS()
    streamer = _streamer(tts)
    assert await streamer.start()
    assert tts._pause_frame_processing is False  # would block without an output transport

    first = await _collect(streamer, "Hello there.")
    second = await _collect(streamer, "Second sentence.")

    assert len(first) == 3 and len(second) == 3
    assert tts.spoken == ["Hello there.", "Second sentence."]
    await streamer.close()


@pytest.mark.asyncio
async def test_mid_sentence_pause_does_not_split_segment():
    """Audio after a provider stall stays in its own sentence (PR review P1)."""
    tts = FakeTTS(chunks=4, pause_after=2, pause_s=0.5)
    streamer = _streamer(tts)
    assert await streamer.start()

    first = await _collect(streamer, "Long sentence with a pause.")
    second = await _collect(streamer, "Next one.")

    assert len(first) == 4 and len(second) == 4
    await streamer.close()


@pytest.mark.asyncio
async def test_stale_stop_frame_before_audio_is_ignored():
    tts = FakeTTS(chunks=2)
    streamer = _streamer(tts)
    assert await streamer.start()

    async def stale_stop_then_speak():
        gen = streamer.synthesize("Hello there.")
        first = asyncio.ensure_future(gen.__anext__())
        while streamer._active is None:  # wait until synthesize() owns the queue
            await asyncio.sleep(0.001)
        streamer._on_stopped()  # stop left over from an interrupted segment
        chunks = [await first]
        async for chunk in gen:
            chunks.append(chunk)
        return chunks

    assert len(await stale_stop_then_speak()) == 2
    await streamer.close()


@pytest.mark.asyncio
async def test_audio_is_resampled_to_bridge_rate():
    tts = FakeTTS(rate=24000, chunks=1)
    streamer = _streamer(tts, sample_rate=16000)
    assert await streamer.start()
    (chunk,) = await _collect(streamer, "Hi.")
    assert len(chunk) == 640 * 2 // 3 // 2 * 2  # 320 samples @24k -> ~213 @16k
    await streamer.close()


@pytest.mark.asyncio
async def test_error_before_audio_raises_for_fallback():
    streamer = _streamer(FakeTTS(fail=True))
    assert await streamer.start()
    with pytest.raises(RuntimeError):
        await _collect(streamer, "Hi.")
    await streamer.close()


@pytest.mark.asyncio
async def test_interrupt_sends_interruption_and_drops_late_audio():
    tts = FakeTTS(chunks=5, delay=0.05)
    streamer = _streamer(tts)
    assert await streamer.start()

    async def first_chunk_then_interrupt():
        async for _ in streamer.synthesize("Long sentence here."):
            await streamer.interrupt()
            return

    await first_chunk_then_interrupt()
    await asyncio.sleep(0.3)
    assert tts.interruptions == 1
    assert streamer._active is None
    await streamer.close()


@pytest.mark.asyncio
async def test_start_failure_returns_false():
    def boom(*args):
        raise ValueError("Unsupported TTS provider")

    streamer = AgentTTSStreamer(provider="nope", api_key="k", sample_rate=16000, service_factory=boom)
    assert await streamer.start() is False
    assert not streamer.healthy


# ----------------------------------------------------------------------
# TestAgentProcessor with a streaming TTS
# ----------------------------------------------------------------------


class FakeStreamer:
    healthy = True

    def __init__(self, *, chunks=4, delay=0.05, fail=False):
        self._chunks, self._delay, self._fail = chunks, delay, fail
        self.interrupted = 0
        self.finished = 0

    async def synthesize(self, text):
        if self._fail:
            raise RuntimeError("no audio")
        for i in range(self._chunks):
            await asyncio.sleep(self._delay)
            yield f"{text}#{i}".encode()

    async def interrupt(self):
        self.interrupted += 1

    async def finish_utterance(self):
        self.finished += 1


def _processor(streamer) -> TestAgentProcessor:
    p = TestAgentProcessor(
        TestAgentConfig(
            organization_id=uuid.uuid4(),
            db=MagicMock(),
            llm_provider="fireworks",
            llm_model="glm-5p3",
            response_delay_ms=0,
        )
    )
    p.tts_streamer = streamer
    return p


def _fake_llm(text):
    def call(self, messages, *, on_text_delta=None, **kwargs):
        if on_text_delta:
            for word in text.split(" "):
                on_text_delta(word + " ")
        return {"text": text}

    return call


@pytest.mark.asyncio
async def test_first_chunk_plays_before_segment_finishes_streaming():
    streamer = FakeStreamer(chunks=4, delay=0.1)
    processor = _processor(streamer)
    sent: list[tuple[float, bytes]] = []
    start = time.monotonic()

    async def speak(audio):
        sent.append((time.monotonic() - start, audio))
        return len(audio)

    with patch.object(TestAgentProcessor, "_sync_llm_call", _fake_llm("Sure, my name is Shubh.")), patch.object(
        TestAgentProcessor, "_record_tts_usage"
    ):
        reply = await processor.process_agent_transcript_streaming("Name?", speak)

    assert reply == "Sure, my name is Shubh."
    assert [a for _, a in sent] == [f"Sure, my name is Shubh.#{i}".encode() for i in range(4)]
    # Chunks are forwarded as they stream in (0.1 s apart), not all at segment end.
    assert sent[-1][0] - sent[0][0] >= 0.25
    assert streamer.finished == 1 and streamer.interrupted == 0


@pytest.mark.asyncio
async def test_barge_in_interrupts_streaming_tts():
    streamer = FakeStreamer(chunks=6, delay=0.01)
    processor = _processor(streamer)
    cancel = asyncio.Event()

    async def speak(audio):
        cancel.set()
        return len(audio) // 2

    with patch.object(TestAgentProcessor, "_sync_llm_call", _fake_llm("One two three four five. Six seven.")), patch.object(
        TestAgentProcessor, "_record_tts_usage"
    ):
        await processor.process_agent_transcript_streaming("Hi", speak, cancel_event=cancel)

    assert streamer.interrupted == 1
    assert processor.conversation_history[-1]["content"].endswith("[interrupted]")


@pytest.mark.asyncio
async def test_streaming_failure_falls_back_to_one_shot_tts():
    processor = _processor(FakeStreamer(fail=True))
    sent: list[bytes] = []

    async def speak(audio):
        sent.append(audio)
        return len(audio)

    async def one_shot(self, text):
        return b"oneshot:" + text.encode()

    with patch.object(TestAgentProcessor, "_sync_llm_call", _fake_llm("Hello there friend.")), patch.object(
        TestAgentProcessor, "_text_to_speech", one_shot
    ):
        await processor.process_agent_transcript_streaming("Hi", speak)

    assert sent == [b"oneshot:Hello there friend."]



@pytest.mark.asyncio
async def test_barge_in_releases_turn_while_llm_is_stalled():
    processor = _processor(FakeStreamer())
    cancel = asyncio.Event()

    def hung_llm(self, messages, *, on_text_delta=None, **kwargs):
        time.sleep(1.0)  # provider stall
        return {"text": ""}

    async def speak(audio):
        return len(audio)

    async def barge_in():
        await asyncio.sleep(0.1)
        cancel.set()

    with patch.object(TestAgentProcessor, "_sync_llm_call", hung_llm):
        start = time.monotonic()
        asyncio.create_task(barge_in())
        await processor.process_agent_transcript_streaming("Hi", speak, cancel_event=cancel)
        assert time.monotonic() - start < 0.5
    assert not processor.is_processing


@pytest.mark.asyncio
async def test_turn_is_skipped_when_llm_produces_no_text_in_time(monkeypatch):
    from app.services.webrtc_bridge import test_agent_processor as tap

    monkeypatch.setattr(tap, "LLM_FIRST_TEXT_TIMEOUT_S", 0.2)
    processor = _processor(FakeStreamer())
    sent = []

    def hung_llm(self, messages, *, on_text_delta=None, **kwargs):
        time.sleep(0.6)
        return {"text": ""}

    async def speak(audio):
        sent.append(audio)
        return len(audio)

    async def must_not_retry(self, messages):
        raise AssertionError("stalled LLM must not be retried")

    with patch.object(TestAgentProcessor, "_sync_llm_call", hung_llm), patch.object(
        TestAgentProcessor, "_generate_via_llm_service", must_not_retry
    ):
        start = time.monotonic()
        reply = await processor.process_agent_transcript_streaming("Hi", speak)
        assert time.monotonic() - start < 0.5
    assert reply is None and sent == []



@pytest.mark.asyncio
async def test_cancelling_synthesis_blocked_on_full_segment_queue_finishes():
    """PR review P1 (direct): cancelling the synthesis worker while it waits on a
    full segment queue must not leave it blocked adding the end marker."""
    processor = _processor(FakeStreamer(chunks=1, delay=0.0))
    segment_q: asyncio.Queue = asyncio.Queue(maxsize=1)
    segment_q.put_nowait(("already queued", asyncio.Queue()))  # player stopped reading
    text_q: asyncio.Queue = asyncio.Queue()
    text_q.put_nowait("Hello there friend. Next one.")
    text_q.put_nowait(None)

    with patch.object(TestAgentProcessor, "_record_tts_usage"):
        task = asyncio.create_task(processor._synthesize_segments(text_q, segment_q, [], lambda: False))
        await asyncio.sleep(0.05)  # worker is now blocked putting its first segment
        task.cancel()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=1.0)
