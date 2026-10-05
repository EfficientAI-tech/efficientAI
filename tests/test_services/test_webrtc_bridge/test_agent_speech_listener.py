"""Unit tests for AgentSpeechListener using a fake streaming STT processor."""

from __future__ import annotations

import asyncio

import pytest

from app.services.webrtc_bridge.agent_speech_listener import AgentSpeechListener
from efficientai.frames.frames import (
    ErrorFrame,
    InputAudioRawFrame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
    UserStoppedSpeakingFrame,
)
from efficientai.processors.frame_processor import FrameDirection, FrameProcessor
from efficientai.utils.time import time_now_iso8601

PCM = b"\x01\x00" * 320  # 20 ms at 16 kHz


class FakeSTT(FrameProcessor):
    """Emits an interim per audio frame and a final on UserStoppedSpeakingFrame."""

    def __init__(self, *, final_text="hello from the agent", emit_final=True, fail_on_audio=False):
        super().__init__()
        self._final_text = final_text
        self._emit_final = emit_final
        self._fail_on_audio = fail_on_audio

    async def process_frame(self, frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame):
            if self._fail_on_audio:
                await self.push_error(ErrorFrame(error="stt socket closed"))
                return
            await self.push_frame(InterimTranscriptionFrame("hello from", "agent", time_now_iso8601()))
            return
        if isinstance(frame, UserStoppedSpeakingFrame) and self._emit_final:
            await self.push_frame(frame, direction)
            await self.push_frame(TranscriptionFrame(self._final_text, "agent", time_now_iso8601()))
            return
        await self.push_frame(frame, direction)


def _listener(stt: FakeSTT, usage: list[float] | None = None) -> AgentSpeechListener:
    return AgentSpeechListener(
        provider="deepgram",
        api_key="test",
        service_factory=lambda *args: stt,
        on_usage=(usage.append if usage is not None else None),
    )


@pytest.mark.asyncio
async def test_finalize_turn_returns_final_transcript():
    usage: list[float] = []
    listener = _listener(FakeSTT(), usage)
    assert await listener.start()

    for _ in range(10):
        await listener.push_audio(PCM)
    text = await listener.finalize_turn(timeout=1.0)

    assert text == "hello from the agent"
    await listener.close()
    assert usage and usage[0] == pytest.approx(0.2, abs=0.01)


@pytest.mark.asyncio
async def test_finalize_turn_falls_back_to_last_partial():
    listener = _listener(FakeSTT(emit_final=False))
    assert await listener.start()

    await listener.push_audio(PCM)
    text = await listener.finalize_turn(timeout=0.2)

    assert text == "hello from"
    await listener.close()


@pytest.mark.asyncio
async def test_finalize_turn_without_audio_returns_none():
    listener = _listener(FakeSTT())
    assert await listener.start()
    assert await listener.finalize_turn(timeout=0.1) is None
    await listener.close()


@pytest.mark.asyncio
async def test_stt_error_marks_listener_unhealthy():
    listener = _listener(FakeSTT(fail_on_audio=True))
    assert await listener.start()

    await listener.push_audio(PCM)
    for _ in range(50):
        if not listener.healthy:
            break
        await __import__("asyncio").sleep(0.01)

    assert not listener.healthy
    await listener.close()


@pytest.mark.asyncio
async def test_start_failure_returns_false():
    def boom(*args):
        raise RuntimeError("no sdk")

    listener = AgentSpeechListener(provider="deepgram", api_key="test", service_factory=boom)
    assert await listener.start() is False
    assert not listener.healthy


class _RecordingSocket:
    def __init__(self):
        self.flushes = 0

    async def flush(self):
        self.flushes += 1


class ServerVADSTT(FrameProcessor):
    """Mimics Sarvam: ignores UserStoppedSpeakingFrame, finalizes on silence or flush."""

    def __init__(self, *, final_delay: float = 0.0):
        super().__init__()
        self._socket_client = _RecordingSocket()
        self.silent_frames = 0
        self._final_delay = final_delay
        self._texts = iter(["turn one text", "turn two text"])

    async def process_frame(self, frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame):
            if not any(frame.audio):
                self.silent_frames += 1
                if self.silent_frames % 30 == 0:  # 0.6 s of trailing silence
                    text = next(self._texts)
                    if self._final_delay:
                        await asyncio.sleep(self._final_delay)
                    await self.push_frame(TranscriptionFrame(text, "agent", time_now_iso8601()))
            return
        await self.push_frame(frame, direction)


@pytest.mark.asyncio
async def test_finalize_pushes_trailing_silence_and_requests_flush():
    stt = ServerVADSTT()
    listener = _listener(stt)
    assert await listener.start()

    for _ in range(5):
        await listener.push_audio(PCM)
    text = await listener.finalize_turn(timeout=1.0)

    assert text == "turn one text"
    assert stt.silent_frames == 30
    assert stt._socket_client.flushes == 1
    await listener.close()


@pytest.mark.asyncio
async def test_late_final_is_not_handed_to_next_turn():
    stt = ServerVADSTT(final_delay=0.3)
    listener = _listener(stt)
    assert await listener.start()

    await listener.push_audio(PCM)
    assert await listener.finalize_turn(timeout=0.05) is None
    await asyncio.sleep(0.4)  # turn one's final lands after the timeout

    await listener.push_audio(PCM)  # next agent turn starts
    stt._final_delay = 0.0
    text = await listener.finalize_turn(timeout=1.0)

    assert text == "turn two text"
    await listener.close()
