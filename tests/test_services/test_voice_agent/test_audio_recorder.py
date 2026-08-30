"""Tests for direction-aware AudioRecorder capture (telephony dual-track)."""

import asyncio
import os
import time
import wave
from unittest.mock import AsyncMock

import numpy as np

from app.services.voice_agent.audio_recorder import get_audio_recorder_class
from efficientai.frames.frames import (
    BotStartedSpeakingFrame,
    EndFrame,
    InputAudioRawFrame,
    OutputAudioRawFrame,
)
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


def test_playout_mode_does_not_compress_burst_audio(tmp_path):
    """A TTS burst arriving faster than real time must keep its full duration.

    Regression test for agent/user overlap: wall_clock mode padded per frame, so a
    burst overshot the clock and subsequent silence was swallowed, pulling bot
    speech earlier than it was heard.
    """

    async def run():
        start = time.time()
        recorder, path = _make_recorder(
            tmp_path, capture="output", alignment_mode="playout", start_time=start
        )
        recorder.push_frame = AsyncMock()

        await recorder.process_frame(BotStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        # 1s of audio (8000 samples) delivered in one burst, i.e. no wall-clock time.
        for _ in range(10):
            await recorder.process_frame(
                OutputAudioRawFrame(
                    audio=_tone_bytes(sample_rate=8000, num_samples=800),
                    sample_rate=8000,
                    num_channels=1,
                ),
                FrameDirection.DOWNSTREAM,
            )
        recorder._close_wave_file(trailing_pad=False)

        # All 8000 audio samples survive; nothing is dropped or compressed.
        # Only the sub-millisecond anchor pad is added on top.
        total = _wav_sample_count(path)
        assert 8000 <= total <= 8100, total

    asyncio.run(run())


def test_playout_mode_anchors_utterance_to_bot_started_speaking(tmp_path):
    """Silence before an utterance reflects when the bot actually started speaking."""

    async def run():
        start = time.time() - 2.0  # call began 2s ago
        recorder, path = _make_recorder(
            tmp_path, capture="output", alignment_mode="playout", start_time=start
        )
        recorder.push_frame = AsyncMock()

        await recorder.process_frame(BotStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await recorder.process_frame(
            OutputAudioRawFrame(
                audio=_tone_bytes(sample_rate=8000, num_samples=800),
                sample_rate=8000,
                num_channels=1,
            ),
            FrameDirection.DOWNSTREAM,
        )
        recorder._close_wave_file(trailing_pad=False)

        # ~2s of leading silence (16000 samples) then the 800 audio samples.
        total = _wav_sample_count(path)
        assert 16000 - 800 <= total - 800 <= 16000 + 800, total

        with wave.open(path, "rb") as wf:
            samples = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
        assert not np.any(samples[:15000])   # leading pad is silent
        assert np.any(samples[-800:])        # utterance landed at the end

    asyncio.run(run())


def test_playout_mode_second_utterance_keeps_real_gap(tmp_path):
    """Two bursts separated by real silence stay separated in the recording."""

    async def run():
        start = time.time()
        recorder, path = _make_recorder(
            tmp_path, capture="output", alignment_mode="playout", start_time=start
        )
        recorder.push_frame = AsyncMock()

        async def utterance():
            await recorder.process_frame(BotStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
            await recorder.process_frame(
                OutputAudioRawFrame(
                    audio=_tone_bytes(sample_rate=8000, num_samples=800),
                    sample_rate=8000,
                    num_channels=1,
                ),
                FrameDirection.DOWNSTREAM,
            )

        await utterance()
        time.sleep(1.0)  # user is speaking here; bot track must stay silent
        await utterance()
        recorder._close_wave_file(trailing_pad=False)

        # 800 + ~1s gap + 800. Under the old wall_clock mode the gap was swallowed.
        total = _wav_sample_count(path)
        assert total >= 8000, total

    asyncio.run(run())
