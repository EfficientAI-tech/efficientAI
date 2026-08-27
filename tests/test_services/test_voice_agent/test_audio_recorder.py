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


def _make_recorder(
    tmp_path,
    *,
    capture: str,
    alignment_mode: str = "stream",
    start_time: float | None = None,
    ambient_bed=None,
):
    AudioRecorder = get_audio_recorder_class()
    path = str(tmp_path / f"{capture}.wav")
    return AudioRecorder(
        path,
        start_time if start_time is not None else time.time(),
        target_sample_rate=8000,
        recorder_name=f"{capture}Recorder",
        alignment_mode=alignment_mode,
        capture=capture,
        ambient_bed=ambient_bed,
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


def test_output_recorder_captures_tts_subclass_frames(tmp_path):
    """Gemini/Cartesia emit TTSAudioRawFrame, which must land on the bot track."""

    async def run():
        from efficientai.frames.frames import TTSAudioRawFrame

        recorder, path = _make_recorder(tmp_path, capture="output")
        recorder.push_frame = AsyncMock()

        tts_audio = _tone_bytes(sample_rate=8000, num_samples=240, freq=880.0)
        await recorder.process_frame(
            TTSAudioRawFrame(audio=tts_audio, sample_rate=8000, num_channels=1),
            FrameDirection.DOWNSTREAM,
        )
        await recorder.process_frame(EndFrame(), FrameDirection.DOWNSTREAM)

        assert _wav_sample_count(path) == 240

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


def test_wall_clock_pads_gaps_longer_than_one_second(tmp_path):
    async def run():
        start = time.time()
        recorder, path = _make_recorder(
            tmp_path,
            capture="output",
            alignment_mode="wall_clock",
            start_time=start,
        )
        recorder.push_frame = AsyncMock()

        first = _tone_bytes(sample_rate=8000, num_samples=160)
        await recorder.process_frame(
            OutputAudioRawFrame(audio=first, sample_rate=8000, num_channels=1),
            FrameDirection.DOWNSTREAM,
        )

        time.sleep(2.0)

        second = _tone_bytes(sample_rate=8000, num_samples=160, freq=880.0)
        await recorder.process_frame(
            OutputAudioRawFrame(audio=second, sample_rate=8000, num_channels=1),
            FrameDirection.DOWNSTREAM,
        )
        await recorder.process_frame(EndFrame(), FrameDirection.DOWNSTREAM)

        sample_count = _wav_sample_count(path)
        assert sample_count >= 16000

    asyncio.run(run())


def test_wall_clock_endframe_pads_trailing_silence(tmp_path):
    async def run():
        start = time.time()
        recorder, path = _make_recorder(
            tmp_path,
            capture="output",
            alignment_mode="wall_clock",
            start_time=start,
        )
        recorder.push_frame = AsyncMock()

        audio = _tone_bytes(sample_rate=8000, num_samples=800)
        await recorder.process_frame(
            OutputAudioRawFrame(audio=audio, sample_rate=8000, num_channels=1),
            FrameDirection.DOWNSTREAM,
        )

        time.sleep(0.5)
        await recorder.process_frame(EndFrame(), FrameDirection.DOWNSTREAM)

        sample_count = _wav_sample_count(path)
        assert sample_count >= 4000

    asyncio.run(run())


def test_output_recorder_mixes_ambient_bed_on_speech(tmp_path):
    from app.services.audio.ambient_mixer import AmbientBed

    async def run():
        bed = AmbientBed(np.array([1000, -1000, 500, -500], dtype=np.int16), volume=0.5)
        recorder, path = _make_recorder(
            tmp_path,
            capture="output",
            alignment_mode="stream",
            ambient_bed=bed,
        )
        recorder.push_frame = AsyncMock()

        speech = np.array([100, 200, 300, 400], dtype=np.int16).tobytes()
        await recorder.process_frame(
            OutputAudioRawFrame(audio=speech, sample_rate=8000, num_channels=1),
            FrameDirection.DOWNSTREAM,
        )
        await recorder.process_frame(EndFrame(), FrameDirection.DOWNSTREAM)

        with wave.open(path, "rb") as wf:
            recorded = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
        assert not np.array_equal(recorded[:4], np.array([100, 200, 300, 400], dtype=np.int16))

    asyncio.run(run())


def test_output_recorder_ambient_bed_fills_gap_pad(tmp_path):
    from app.services.audio.ambient_mixer import AmbientBed

    async def run():
        start = time.time()
        bed = AmbientBed(np.array([8000, -8000, 4000, -4000], dtype=np.int16), volume=0.5)
        recorder, path = _make_recorder(
            tmp_path,
            capture="output",
            alignment_mode="wall_clock",
            start_time=start,
            ambient_bed=bed,
        )
        recorder.push_frame = AsyncMock()

        first = _tone_bytes(sample_rate=8000, num_samples=160)
        await recorder.process_frame(
            OutputAudioRawFrame(audio=first, sample_rate=8000, num_channels=1),
            FrameDirection.DOWNSTREAM,
        )

        time.sleep(0.25)

        second = _tone_bytes(sample_rate=8000, num_samples=160, freq=880.0)
        await recorder.process_frame(
            OutputAudioRawFrame(audio=second, sample_rate=8000, num_channels=1),
            FrameDirection.DOWNSTREAM,
        )
        await recorder.process_frame(EndFrame(), FrameDirection.DOWNSTREAM)

        with wave.open(path, "rb") as wf:
            recorded = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
        gap_region = recorded[160:800]
        assert np.any(gap_region != 0)

    asyncio.run(run())
