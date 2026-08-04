"""Tests for call silence hangup processor."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.voice_agent.call_silence_hangup import (
    CallSilenceHangupProcessor,
    resolve_agent_silence_hangup_secs,
)
from efficientai.frames.frames import BotSpeakingFrame, EndFrame, UserStartedSpeakingFrame
from efficientai.processors.frame_processor import FrameDirection


def test_resolve_agent_silence_hangup_defaults():
    assert resolve_agent_silence_hangup_secs(None) == 15.0
    assert resolve_agent_silence_hangup_secs(SimpleNamespace(silence_hangup_secs=None)) == 15.0


def test_resolve_agent_silence_hangup_disabled_and_custom():
    assert resolve_agent_silence_hangup_secs(SimpleNamespace(silence_hangup_secs=0)) is None
    assert resolve_agent_silence_hangup_secs(SimpleNamespace(silence_hangup_secs=30)) == 30.0


@pytest.mark.asyncio
async def test_trigger_hangup_pushes_end_frame():
    hangup_cb = AsyncMock()
    processor = CallSilenceHangupProcessor(timeout_secs=15.0, on_hangup=hangup_cb)
    pushed = []

    async def capture(frame, direction):
        pushed.append(frame)

    processor.push_frame = capture

    await processor._trigger_hangup()

    hangup_cb.assert_awaited_once()
    assert len(pushed) == 1
    assert isinstance(pushed[0], EndFrame)


@pytest.mark.asyncio
async def test_speech_frames_touch_activity(monkeypatch):
    monkeypatch.setattr(
        "app.services.voice_agent.call_silence_hangup.time.monotonic",
        lambda: 42.0,
    )
    processor = CallSilenceHangupProcessor(timeout_secs=15.0)
    processor.push_frame = AsyncMock()

    await processor.process_frame(UserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    assert processor._last_activity == 42.0

    monkeypatch.setattr(
        "app.services.voice_agent.call_silence_hangup.time.monotonic",
        lambda: 99.0,
    )
    await processor.process_frame(BotSpeakingFrame(), FrameDirection.DOWNSTREAM)
    assert processor._last_activity == 99.0
