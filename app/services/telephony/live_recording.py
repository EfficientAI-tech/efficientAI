"""Read in-progress telephony WAV captures and build partial mono playback."""

from __future__ import annotations

import io
import os
import struct
import wave
from typing import Tuple

import numpy as np


def _parse_wav_pcm(raw: bytes) -> Tuple[np.ndarray, int]:
    """Parse PCM mono samples from a possibly incomplete WAV file."""
    if len(raw) < 44 or raw[:4] != b"RIFF":
        return np.array([], dtype=np.int16), 0

    sample_rate = 0
    num_channels = 1
    bits_per_sample = 16
    data_start: int | None = None

    pos = 12
    while pos + 8 <= len(raw):
        chunk_id = raw[pos : pos + 4]
        chunk_size = struct.unpack("<I", raw[pos + 4 : pos + 8])[0]
        chunk_data_start = pos + 8
        if chunk_id == b"fmt " and chunk_size >= 16:
            num_channels = struct.unpack("<H", raw[chunk_data_start + 2 : chunk_data_start + 4])[0]
            sample_rate = struct.unpack("<I", raw[chunk_data_start + 4 : chunk_data_start + 8])[0]
            if chunk_size >= 16:
                bits_per_sample = struct.unpack("<H", raw[chunk_data_start + 14 : chunk_data_start + 16])[0]
        elif chunk_id == b"data":
            data_start = chunk_data_start
            break
        pos = chunk_data_start + chunk_size
        if chunk_size % 2:
            pos += 1

    if data_start is None or sample_rate <= 0:
        return np.array([], dtype=np.int16), 0

    pcm_bytes = raw[data_start:]
    bytes_per_frame = max(1, num_channels * (bits_per_sample // 8))
    trim = (len(pcm_bytes) // bytes_per_frame) * bytes_per_frame
    if trim < bytes_per_frame:
        return np.array([], dtype=np.int16), sample_rate

    samples = np.frombuffer(pcm_bytes[:trim], dtype=np.int16)
    if num_channels > 1:
        samples = samples.reshape(-1, num_channels).mean(axis=1).astype(np.int16)
    return samples, sample_rate


def read_growing_wav_mono(path: str) -> Tuple[np.ndarray, int]:
    """Read whatever PCM has been flushed to a growing WAV capture file."""
    if not path or not os.path.isfile(path):
        return np.array([], dtype=np.int16), 0
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError:
        return np.array([], dtype=np.int16), 0
    return _parse_wav_pcm(raw)


def pcm_to_wav_bytes(samples: np.ndarray, sample_rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(samples.astype(np.int16).tobytes())
    return buffer.getvalue()


def merge_live_tracks_mono(user_path: str, bot_path: str) -> Tuple[bytes, float, int]:
    """Merge partial user/bot telephony tracks into a mono WAV for live playback."""
    user, sr_user = read_growing_wav_mono(user_path)
    bot, sr_bot = read_growing_wav_mono(bot_path)

    sample_rate = sr_user or sr_bot or 24000
    if len(user) == 0 and len(bot) == 0:
        return b"", 0.0, sample_rate

    if len(user) == 0:
        mixed = bot
    elif len(bot) == 0:
        mixed = user
    else:
        target_len = max(len(user), len(bot))
        user_pad = np.pad(user, (0, target_len - len(user))) if len(user) < target_len else user[:target_len]
        bot_pad = np.pad(bot, (0, target_len - len(bot))) if len(bot) < target_len else bot[:target_len]
        mixed = ((user_pad.astype(np.int32) + bot_pad.astype(np.int32)) // 2).astype(np.int16)

    duration_sec = len(mixed) / float(sample_rate) if sample_rate > 0 else 0.0
    return pcm_to_wav_bytes(mixed, sample_rate), duration_sec, sample_rate
