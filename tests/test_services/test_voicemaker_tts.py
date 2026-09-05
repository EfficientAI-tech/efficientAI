"""Tests for VoiceMaker WebSocket TTS receive handling."""

from __future__ import annotations

import base64
import json
from typing import Any, Iterator, List

import pytest

from efficientai.frames.frames import ErrorFrame, TTSAudioRawFrame, TTSStoppedFrame
from efficientai.processors.frame_processor import FrameDirection
from efficientai.services.voicemaker.tts import VoiceMakerTTSService


class _AsyncMessageStream:
    """Minimal async iterable mimicking a VoiceMaker websocket message stream."""

    def __init__(self, messages: Iterator[Any]):
        self._messages = messages

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._messages)
        except StopIteration:
            raise StopAsyncIteration from None


@pytest.fixture
def voicemaker_tts() -> VoiceMakerTTSService:
    return VoiceMakerTTSService(api_key="test-key", voice_id="ai3-Jony", sample_rate=24000)


async def _collect_receive_frames(
    service: VoiceMakerTTSService,
    messages: List[Any],
) -> List[Any]:
    pushed: List[Any] = []

    async def capture(frame, direction: FrameDirection = FrameDirection.DOWNSTREAM):
        pushed.append(frame)

    service.push_frame = capture  # type: ignore[method-assign]
    service._websocket = _AsyncMessageStream(iter(messages))
    await service._receive_messages()
    return pushed


@pytest.mark.asyncio
async def test_receive_messages_skips_empty_string(voicemaker_tts):
    frames = await _collect_receive_frames(voicemaker_tts, ["", "   "])
    assert frames == []


@pytest.mark.asyncio
async def test_receive_messages_skips_binary_frames(voicemaker_tts):
    frames = await _collect_receive_frames(voicemaker_tts, [b"\x00\x01\x02"])
    assert frames == []


@pytest.mark.asyncio
async def test_receive_messages_ignores_non_json_without_raising(voicemaker_tts):
    frames = await _collect_receive_frames(
        voicemaker_tts,
        ["<!DOCTYPE html><html><body>403 Forbidden</body></html>"],
    )
    assert frames == []


@pytest.mark.asyncio
async def test_receive_messages_pushes_error_frame_on_success_false(voicemaker_tts):
    frames = await _collect_receive_frames(
        voicemaker_tts,
        [json.dumps({"success": False, "message": "Invalid voice"})],
    )
    assert len(frames) == 1
    assert isinstance(frames[0], ErrorFrame)
    assert "Invalid voice" in frames[0].error


@pytest.mark.asyncio
async def test_receive_messages_emits_audio_and_stopped_on_valid_final_chunk(voicemaker_tts):
    pcm = b"\x01\x00" * 50
    payload = {
        "success": True,
        "audio": base64.b64encode(pcm).decode("ascii"),
        "isFinal": True,
    }
    frames = await _collect_receive_frames(voicemaker_tts, [json.dumps(payload)])

    audio_frames = [frame for frame in frames if isinstance(frame, TTSAudioRawFrame)]
    stopped_frames = [frame for frame in frames if isinstance(frame, TTSStoppedFrame)]
    assert len(audio_frames) == 1
    assert audio_frames[0].audio == pcm
    assert audio_frames[0].sample_rate == 24000
    assert len(stopped_frames) == 1
    assert voicemaker_tts._started is False


@pytest.mark.asyncio
async def test_receive_messages_continues_after_non_json_then_valid_audio(voicemaker_tts):
    pcm = b"\x02\x00" * 20
    valid = json.dumps(
        {
            "success": True,
            "audio": base64.b64encode(pcm).decode("ascii"),
            "isFinal": True,
        }
    )
    frames = await _collect_receive_frames(voicemaker_tts, ["", "<html>proxy</html>", valid])

    audio_frames = [frame for frame in frames if isinstance(frame, TTSAudioRawFrame)]
    assert len(audio_frames) == 1
    assert audio_frames[0].audio == pcm
