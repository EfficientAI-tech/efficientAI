"""Audio capture for telephony and playground pipelines."""

from __future__ import annotations

import time
import wave
from typing import Literal

import numpy as np
from loguru import logger

_audio_recorder_class = None


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
        ):
            super().__init__()
            self.filename = filename
            self.start_time = start_time
            self.target_sample_rate = target_sample_rate
            self.recorder_name = recorder_name
            self.alignment_mode = alignment_mode
            self.capture = capture
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

        def _should_capture(self, frame: AudioRawFrame, direction: FrameDirection) -> bool:
            if direction != FrameDirection.DOWNSTREAM:
                return False
            if self.capture == "input":
                return isinstance(frame, InputAudioRawFrame)
            return isinstance(frame, OutputAudioRawFrame)

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
                            self._write_audio(audio_to_write, self.num_channels)
                            self.last_frame_time = current_time
                        else:
                            elapsed_time = current_time - self.start_time
                            expected_samples = int(elapsed_time * self.sample_rate)
                            if expected_samples > self.total_samples_written:
                                samples_to_pad = expected_samples - self.total_samples_written
                                if samples_to_pad <= self.sample_rate:
                                    silence_bytes = b"\x00" * (
                                        samples_to_pad * self.num_channels * 2
                                    )
                                    self.wave_file.writeframes(silence_bytes)
                                    self.total_samples_written += samples_to_pad

                            self._write_audio(audio_to_write, self.num_channels)
                            self.last_frame_time = current_time
                    except Exception as e:
                        logger.error(f"Error writing audio frame: {e}")

            elif isinstance(frame, (EndFrame, CancelFrame)):
                if self.wave_file:
                    self.wave_file.close()
                    self.wave_file = None

            await self.push_frame(frame, direction)

        async def cleanup(self):
            if self.wave_file:
                self.wave_file.close()
                self.wave_file = None

    _audio_recorder_class = AudioRecorder
    return _audio_recorder_class
