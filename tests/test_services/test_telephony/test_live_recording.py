"""Tests for live telephony recording merge helpers."""

from __future__ import annotations

import struct
import wave
from pathlib import Path

import numpy as np

from app.services.telephony.live_recording import merge_live_tracks_mono, read_growing_wav_mono


def _write_wav(path: Path, samples: np.ndarray, sample_rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(samples.astype(np.int16).tobytes())


def test_read_growing_wav_mono_reads_partial_file(tmp_path: Path) -> None:
    samples = np.array([1000, -1000, 2000, -2000], dtype=np.int16)
    path = tmp_path / "partial.wav"
    _write_wav(path, samples)

    # Simulate a growing file by truncating after header + partial PCM.
    raw = path.read_bytes()
    partial = raw[:44 + 4]
    partial_path = tmp_path / "growing.wav"
    partial_path.write_bytes(partial)

    pcm, sample_rate = read_growing_wav_mono(str(partial_path))
    assert sample_rate == 16000
    assert len(pcm) == 2


def test_merge_live_tracks_mono_mixes_user_and_bot(tmp_path: Path) -> None:
    user_path = tmp_path / "user.wav"
    bot_path = tmp_path / "bot.wav"
    _write_wav(user_path, np.array([1000, 0, 1000, 0], dtype=np.int16))
    _write_wav(bot_path, np.array([0, 1000, 0, 1000], dtype=np.int16))

    wav_bytes, duration_sec, sample_rate = merge_live_tracks_mono(str(user_path), str(bot_path))
    assert sample_rate == 16000
    assert duration_sec > 0
    assert wav_bytes.startswith(b"RIFF")

    merged_path = tmp_path / "merged-out.wav"
    merged_path.write_bytes(wav_bytes)
    merged, merged_rate = read_growing_wav_mono(str(merged_path))
    assert merged_rate == 16000
    assert len(merged) == 4
    assert merged[0] == 500
