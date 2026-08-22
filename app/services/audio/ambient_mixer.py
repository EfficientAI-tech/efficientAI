"""Ambient background audio mixing for test-agent caller simulation."""

from __future__ import annotations

import io
from typing import Optional

import numpy as np
from loguru import logger

from efficientai.audio.mixers.base_audio_mixer import BaseAudioMixer
from efficientai.frames.frames import MixerControlFrame

DEFAULT_AMBIENT_VOLUME = 0.22
MIN_AMBIENT_VOLUME = 0.05
MAX_AMBIENT_VOLUME = 0.60


def clamp_ambient_volume(volume: Optional[float]) -> float:
    if volume is None:
        return DEFAULT_AMBIENT_VOLUME
    return float(max(MIN_AMBIENT_VOLUME, min(MAX_AMBIENT_VOLUME, volume)))


def resample_mono_int16(audio: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate or len(audio) == 0:
        return audio.astype(np.int16, copy=False)
    target_len = max(1, int(round(len(audio) * target_rate / source_rate)))
    try:
        from scipy.signal import resample

        resampled = resample(audio.astype(np.float64), target_len)
    except Exception:
        source_positions = np.linspace(0, len(audio) - 1, num=len(audio))
        target_positions = np.linspace(0, len(audio) - 1, num=target_len)
        resampled = np.interp(target_positions, source_positions, audio.astype(np.float64))
    return np.clip(np.round(resampled), -32768, 32767).astype(np.int16)


def decode_audio_bytes_to_pcm_int16(file_bytes: bytes, target_sample_rate: int) -> np.ndarray:
    """Decode arbitrary audio bytes to mono int16 PCM at target sample rate."""
    try:
        import soundfile as sf
    except ModuleNotFoundError as exc:
        raise RuntimeError("soundfile is required for ambient audio decoding") from exc

    data, sample_rate = sf.read(io.BytesIO(file_bytes), dtype="float32", always_2d=False)
    if data.ndim > 1:
        data = np.mean(data, axis=1)
    pcm = np.clip(data * 32767.0, -32768, 32767).astype(np.int16)
    return resample_mono_int16(pcm, int(sample_rate), target_sample_rate)


class AmbientBed:
    """Looping mono int16 bed used by bridge pumps and transport mixers."""

    def __init__(
        self,
        bed_pcm: np.ndarray,
        *,
        volume: float = DEFAULT_AMBIENT_VOLUME,
        loop: bool = True,
    ):
        self._bed = np.asarray(bed_pcm, dtype=np.int16)
        if self._bed.size == 0:
            raise ValueError("ambient bed PCM must not be empty")
        self._volume = clamp_ambient_volume(volume)
        self._loop = loop
        self._pos = 0

    @property
    def volume(self) -> float:
        return self._volume

    def chunk(self, num_samples: int) -> np.ndarray:
        if num_samples <= 0:
            return np.zeros(0, dtype=np.int16)
        if not self._loop and self._pos >= len(self._bed):
            return np.zeros(num_samples, dtype=np.int16)

        out = np.empty(num_samples, dtype=np.int16)
        offset = 0
        while offset < num_samples:
            if self._pos >= len(self._bed):
                if not self._loop:
                    out[offset:] = 0
                    break
                self._pos = 0
            take = min(num_samples - offset, len(self._bed) - self._pos)
            segment = self._bed[self._pos : self._pos + take]
            out[offset : offset + take] = np.clip(
                np.round(segment.astype(np.float64) * self._volume),
                -32768,
                32767,
            ).astype(np.int16)
            self._pos += take
            offset += take
        return out

    def chunk_bytes(self, num_samples: int) -> bytes:
        return self.chunk(num_samples).tobytes()

    def mix_speech(self, speech_bytes: bytes) -> bytes:
        if not speech_bytes:
            return speech_bytes
        speech = np.frombuffer(speech_bytes, dtype=np.int16)
        bed = self.chunk(len(speech))
        mixed = np.clip(
            speech.astype(np.int32) + bed.astype(np.int32),
            -32768,
            32767,
        ).astype(np.int16)
        return mixed.tobytes()


class AmbientMixer(BaseAudioMixer):
    """Output-transport mixer that overlays a looping ambient bed on bot TTS audio."""

    def __init__(self, bed: AmbientBed):
        self._bed = bed
        self._sample_rate = 0
        self._enabled = True

    @classmethod
    def from_pcm_bytes(
        cls,
        file_bytes: bytes,
        *,
        sample_rate: int,
        volume: Optional[float] = None,
    ) -> "AmbientMixer":
        pcm = decode_audio_bytes_to_pcm_int16(file_bytes, sample_rate)
        return cls(AmbientBed(pcm, volume=clamp_ambient_volume(volume)))

    @classmethod
    def from_pcm_array(
        cls,
        pcm: np.ndarray,
        *,
        volume: Optional[float] = None,
    ) -> "AmbientMixer":
        return cls(AmbientBed(np.asarray(pcm, dtype=np.int16), volume=clamp_ambient_volume(volume)))

    @property
    def bed(self) -> AmbientBed:
        return self._bed

    async def start(self, sample_rate: int):
        self._sample_rate = sample_rate

    async def stop(self):
        pass

    async def process_frame(self, frame: MixerControlFrame):
        del frame

    async def mix(self, audio: bytes) -> bytes:
        if not self._enabled:
            return audio
        if not audio:
            samples = max(1, self._sample_rate // 50) if self._sample_rate else 320
            return self._bed.chunk_bytes(samples)
        return self._bed.mix_speech(audio)
