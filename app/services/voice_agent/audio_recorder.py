"""Audio capture for telephony and playground pipelines."""

from __future__ import annotations

import time
import wave
from typing import TYPE_CHECKING, Literal, Optional

import numpy as np
from loguru import logger

if TYPE_CHECKING:
    from app.services.audio.ambient_mixer import AmbientBed

_audio_recorder_class = None

# Safety cap: refuse to pad more than 30 minutes in one gap (bad clock / hung call).
_MAX_WALL_CLOCK_PAD_SAMPLES = 30 * 60 * 8000


def get_audio_recorder_class():
    """Return the AudioRecorder FrameProcessor subclass (lazy efficientai import)."""
    global _audio_recorder_class
    if _audio_recorder_class is not None:
        return _audio_recorder_class

    from efficientai.frames.frames import (
        AudioRawFrame,
        CancelFrame,
        EndFrame,
        InputAudioRawFrame,
        OutputAudioRawFrame,
    )
    from efficientai.processors.frame_processor import FrameDirection, FrameProcessor

    class AudioRecorder(FrameProcessor):
        def __init__(
            self,
            filename: str,
            start_time: float,
            target_sample_rate: int = 24000,
            recorder_name: str = "AudioRecorder",
            alignment_mode: str = "wall_clock",
            capture: Literal["input", "output"] = "input",
            ambient_bed: Optional["AmbientBed"] = None,
        ):
            super().__init__()
            self.filename = filename
            self.start_time = start_time
            self.target_sample_rate = target_sample_rate
            self.recorder_name = recorder_name
            self.alignment_mode = alignment_mode
            self.capture = capture
            self.ambient_bed = ambient_bed
            self.wave_file = None
            self.params_set = False
            self.sample_rate = 0
            self.num_channels = 0
            self.frames_received = 0
            self.audio_frames_received = 0
            self.last_frame_time = None
            self.total_samples_written = 0

        def _resample_audio(
            self, audio_bytes: bytes, in_rate: int, out_rate: int, num_channels: int
        ) -> bytes:
            if in_rate == out_rate:
                return audio_bytes

            audio_array = np.frombuffer(audio_bytes, dtype=np.int16)
            if num_channels > 1:
                audio_array = audio_array.reshape(-1, num_channels)

            ratio = out_rate / in_rate
            original_length = len(audio_array)
            new_length = int(original_length * ratio)
            old_indices = np.arange(original_length)
            new_indices = np.linspace(0, original_length - 1, new_length)

            if num_channels > 1:
                resampled = np.zeros((new_length, num_channels), dtype=np.int16)
                for ch in range(num_channels):
                    resampled[:, ch] = np.interp(
                        new_indices, old_indices, audio_array[:, ch]
                    ).astype(np.int16)
                return resampled.tobytes()

            resampled = np.interp(new_indices, old_indices, audio_array).astype(np.int16)
            return resampled.tobytes()

        def _write_audio(self, audio_to_write: bytes, num_channels: int) -> None:
            num_samples = len(audio_to_write) // (num_channels * 2)
            self.wave_file.writeframes(audio_to_write)
            self.total_samples_written += num_samples

        def _prepare_audio_bytes(self, audio_bytes: bytes) -> bytes:
            if not audio_bytes:
                return audio_bytes
            if self.ambient_bed is not None:
                return self.ambient_bed.mix_speech(audio_bytes)
            return audio_bytes

        def _pad_bytes(self, num_samples: int, num_channels: int) -> bytes:
            if num_samples <= 0:
                return b""
            if self.ambient_bed is not None:
                bed_mono = self.ambient_bed.chunk_bytes(num_samples)
                if num_channels == 1:
                    return bed_mono
                bed_arr = np.frombuffer(bed_mono, dtype=np.int16)
                return np.repeat(bed_arr, num_channels).astype(np.int16).tobytes()
            return b"\x00" * (num_samples * num_channels * 2)

        def _write_wall_clock_pad(self, current_time: float) -> None:
            elapsed_time = current_time - self.start_time
            expected_samples = int(elapsed_time * self.sample_rate)
            if expected_samples <= self.total_samples_written:
                return

            samples_to_pad = expected_samples - self.total_samples_written
            max_pad = max(
                _MAX_WALL_CLOCK_PAD_SAMPLES,
                self.sample_rate * 60,
            )
            if samples_to_pad > max_pad:
                logger.warning(
                    "{} skipping excessive wall-clock pad: {} samples (cap {})",
                    self.recorder_name,
                    samples_to_pad,
                    max_pad,
                )
                samples_to_pad = max_pad

            chunk_size = self.sample_rate
            remaining = samples_to_pad
            while remaining > 0:
                write_samples = min(remaining, chunk_size)
                pad_bytes = self._pad_bytes(write_samples, self.num_channels)
                self.wave_file.writeframes(pad_bytes)
                self.total_samples_written += write_samples
                remaining -= write_samples

        def _should_capture(self, frame: AudioRawFrame, direction: FrameDirection) -> bool:
            if direction != FrameDirection.DOWNSTREAM:
                return False
            if self.capture == "input":
                return isinstance(frame, InputAudioRawFrame)
            return isinstance(frame, OutputAudioRawFrame)

        def _close_wave_file(self, *, trailing_pad: bool = False) -> None:
            if not self.wave_file:
                return
            try:
                if trailing_pad and self.alignment_mode == "wall_clock" and self.params_set:
                    self._write_wall_clock_pad(time.time())
            except Exception as e:
                logger.error(f"Error writing trailing pad for {self.recorder_name}: {e}")
            finally:
                self.wave_file.close()
                self.wave_file = None

        async def process_frame(self, frame, direction):
            await super().process_frame(frame, direction)
            self.frames_received += 1

            if isinstance(frame, AudioRawFrame) and self._should_capture(frame, direction):
                self.audio_frames_received += 1
                if not self.wave_file:
                    try:
                        self.wave_file = wave.open(self.filename, "wb")
                        self.num_channels = frame.num_channels
                        self.sample_rate = self.target_sample_rate
                        self.wave_file.setnchannels(self.num_channels)
                        self.wave_file.setsampwidth(2)
                        self.wave_file.setframerate(self.sample_rate)
                        self.params_set = True
                    except Exception as e:
                        logger.error(f"Failed to open wave file {self.filename}: {e}")

                if self.wave_file and self.params_set:
                    try:
                        current_time = time.time()
                        if frame.sample_rate != self.sample_rate:
                            audio_to_write = self._resample_audio(
                                frame.audio,
                                frame.sample_rate,
                                self.sample_rate,
                                frame.num_channels,
                            )
                        else:
                            audio_to_write = frame.audio

                        if frame.num_channels != self.num_channels:
                            logger.warning(
                                f"Channel mismatch: expected {self.num_channels}ch, "
                                f"got {frame.num_channels}ch. Skipping frame."
                            )
                        elif self.alignment_mode == "stream":
                            audio_to_write = self._prepare_audio_bytes(audio_to_write)
                            self._write_audio(audio_to_write, self.num_channels)
                            self.last_frame_time = current_time
                        else:
                            self._write_wall_clock_pad(current_time)
                            audio_to_write = self._prepare_audio_bytes(audio_to_write)
                            self._write_audio(audio_to_write, self.num_channels)
                            self.last_frame_time = current_time
                    except Exception as e:
                        logger.error(f"Error writing audio frame: {e}")

            elif isinstance(frame, (EndFrame, CancelFrame)):
                self._close_wave_file(trailing_pad=True)

            await self.push_frame(frame, direction)

        async def cleanup(self):
            self._close_wave_file(trailing_pad=True)

    _audio_recorder_class = AudioRecorder
    return _audio_recorder_class
