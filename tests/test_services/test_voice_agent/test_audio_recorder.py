"""Tests for direction-aware AudioRecorder capture (telephony dual-track)."""

import asyncio
import os
import time
import wave
from unittest.mock import AsyncMock

import numpy as np

from app.services.voice_agent.audio_recorder import get_audio_recorder_class
from efficientai.frames.frames import EndFrame, InputAudioRawFrame, OutputAudioRawFrame
from efficientai.processors.frame_processor import FrameDirection


def _tone_bytes(*, sample_rate: int, num_samples: int, freq: float = 440.0) -> bytes:
    t = np.arange(num_samples, dtype=np.float32) / sample_rate
    samples = (np.sin(2 * np.pi * freq * t) * 16000).astype(np.int16)
    return samples.tobytes()


def _wav_sample_count(path: str) -> int:
    with wave.open(path, "rb") as wf:
        return wf.getnframes()


def _make_recorder(tmp_path, *, capture: str, alignment_mode: str = "stream"):
    AudioRecorder = get_audio_recorder_class()
    path = str(tmp_path / f"{capture}.wav")
    return AudioRecorder(
        path,
        time.time(),
        target_sample_rate=8000,
        recorder_name=f"{capture}Recorder",
        alignment_mode=alignment_mode,
        capture=capture,
    ), path


def test_input_recorder_writes_input_ignores_output(tmp_path):
    async def run():
        recorder, path = _make_recorder(tmp_path, capture="input")
        recorder.push_frame = AsyncMock()

        input_audio = _tone_bytes(sample_rate=8000, num_samples=160)
        output_audio = _tone_bytes(sample_rate=8000, num_samples=320, freq=880.0)

        await recorder.process_frame(
            InputAudioRawFrame(audio=input_audio, sample_rate=8000, num_channels=1),
            FrameDirection.DOWNSTREAM,
        )
        await recorder.process_frame(
            OutputAudioRawFrame(audio=output_audio, sample_rate=8000, num_channels=1),
            FrameDirection.DOWNSTREAM,
        )
        await recorder.process_frame(EndFrame(), FrameDirection.DOWNSTREAM)

        assert _wav_sample_count(path) == 160

    asyncio.run(run())


def test_output_recorder_writes_output_ignores_input(tmp_path):
    async def run():
        recorder, path = _make_recorder(tmp_path, capture="output")
        recorder.push_frame = AsyncMock()

        input_audio = _tone_bytes(sample_rate=8000, num_samples=160)
        output_audio = _tone_bytes(sample_rate=8000, num_samples=320, freq=880.0)

        await recorder.process_frame(
            InputAudioRawFrame(audio=input_audio, sample_rate=8000, num_channels=1),
            FrameDirection.DOWNSTREAM,
        )
        await recorder.process_frame(
            OutputAudioRawFrame(audio=output_audio, sample_rate=8000, num_channels=1),
            FrameDirection.DOWNSTREAM,
        )
        await recorder.process_frame(EndFrame(), FrameDirection.DOWNSTREAM)

        assert _wav_sample_count(path) == 320

    asyncio.run(run())


def test_output_recorder_ignores_upstream_output_frames(tmp_path):
    async def run():
        recorder, path = _make_recorder(tmp_path, capture="output")
        recorder.push_frame = AsyncMock()

        output_audio = _tone_bytes(sample_rate=8000, num_samples=200, freq=880.0)
        await recorder.process_frame(
            OutputAudioRawFrame(audio=output_audio, sample_rate=8000, num_channels=1),
            FrameDirection.UPSTREAM,
        )
        await recorder.process_frame(EndFrame(), FrameDirection.DOWNSTREAM)

        assert not os.path.exists(path)

    asyncio.run(run())


def test_output_recorder_mixed_sequence_excludes_caller_passthrough(tmp_path):
    """Simulates STT/Gemini forwarding caller audio then TTS — bot track must be TTS only."""

    async def run():
        recorder, path = _make_recorder(tmp_path, capture="output")
        recorder.push_frame = AsyncMock()

        caller_chunk = _tone_bytes(sample_rate=8000, num_samples=400, freq=300.0)
        tts_chunk = _tone_bytes(sample_rate=8000, num_samples=600, freq=900.0)

        await recorder.process_frame(
            InputAudioRawFrame(audio=caller_chunk, sample_rate=8000, num_channels=1),
            FrameDirection.DOWNSTREAM,
        )
        await recorder.process_frame(
            InputAudioRawFrame(audio=caller_chunk, sample_rate=8000, num_channels=1),
            FrameDirection.DOWNSTREAM,
        )
        await recorder.process_frame(
            OutputAudioRawFrame(audio=tts_chunk, sample_rate=8000, num_channels=1),
            FrameDirection.DOWNSTREAM,
        )
        await recorder.process_frame(EndFrame(), FrameDirection.DOWNSTREAM)

        assert _wav_sample_count(path) == 600

    asyncio.run(run())
