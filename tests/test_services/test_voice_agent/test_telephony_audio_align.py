"""Unit tests for telephony dual-track merge and alignment."""

import tempfile
import wave

import numpy as np
import pytest

from app.services.voice_agent.utils.telephony_audio_align import (
    TelephonyMergeStrategy,
    analyze_dual_tracks,
    merge_telephony_tracks_to_mono,
    merge_telephony_tracks_to_stereo,
    merge_wall_clock_tracks_to_mono,
    merge_wall_clock_tracks_to_stereo,
    mix_aligned_mono,
    write_wav_mono,
)


def _write_test_wav(path: str, samples: np.ndarray, sample_rate: int = 8000) -> None:
    write_wav_mono(path, samples.astype(np.int16), sample_rate)


def test_analyze_dual_tracks_user_only_when_bot_echo_on_inbound():
    sample_rate = 8000
    bot = (np.sin(np.linspace(0, 20 * np.pi, sample_rate)) * 12000).astype(np.int16)
    user = bot.copy()

    analysis = analyze_dual_tracks(user, bot, sample_rate=sample_rate)
    assert analysis.strategy == TelephonyMergeStrategy.USER_ONLY
    assert analysis.reason == "bot_energy_on_inbound_leg"


def test_analyze_dual_tracks_aligned_mix_for_independent_tracks():
    sample_rate = 8000
    t = np.linspace(0, 1, sample_rate, endpoint=False)
    user = (np.sin(2 * np.pi * 300 * t) * 10000).astype(np.int16)
    bot = (np.sin(2 * np.pi * 900 * t) * 8000).astype(np.int16)

    analysis = analyze_dual_tracks(user, bot, sample_rate=sample_rate)
    assert analysis.strategy == TelephonyMergeStrategy.ALIGNED_MIX


def test_mix_aligned_mono_normalized_reduces_clipping():
    sample_rate = 8000
    user = np.full(sample_rate, 20000, dtype=np.int16)
    bot = np.full(sample_rate, 20000, dtype=np.int16)

    normalized = mix_aligned_mono(user, bot, bot_delay_samples=0, normalize=True)
    raw = mix_aligned_mono(user, bot, bot_delay_samples=0, normalize=False)

    assert np.max(np.abs(normalized)) <= 32767
    assert np.max(np.abs(raw)) == 32767


def test_merge_telephony_tracks_outputs_stereo_and_mono(tmp_path):
    sample_rate = 8000
    duration = sample_rate
    t = np.linspace(0, 1, duration, endpoint=False)
    user = (np.sin(2 * np.pi * 220 * t) * 10000).astype(np.int16)
    bot = (np.sin(2 * np.pi * 440 * t) * 8000).astype(np.int16)

    user_path = tmp_path / "user.wav"
    bot_path = tmp_path / "bot.wav"
    stereo_path = tmp_path / "stereo.wav"
    mono_path = tmp_path / "mono.wav"
    _write_test_wav(str(user_path), user, sample_rate)
    _write_test_wav(str(bot_path), bot, sample_rate)

    stereo_analysis, stereo_duration = merge_telephony_tracks_to_stereo(
        str(user_path),
        str(bot_path),
        output_path=str(stereo_path),
    )
    mono_analysis, mono_duration = merge_telephony_tracks_to_mono(
        str(user_path),
        str(bot_path),
        output_path=str(mono_path),
    )

    assert stereo_path.exists()
    assert mono_path.exists()
    assert stereo_duration > 0
    assert mono_duration > 0
    assert stereo_analysis.strategy == mono_analysis.strategy

    with wave.open(str(stereo_path), "rb") as wf:
        assert wf.getnchannels() == 2
        assert wf.getframerate() == sample_rate
        assert wf.getnframes() > 0

    with wave.open(str(mono_path), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getnframes() > 0


def test_merge_wall_clock_stereo_does_not_add_telephony_bot_delay(tmp_path):
    sample_rate = 8000
    user = np.zeros(sample_rate, dtype=np.int16)
    user[1000:2000] = 5000
    bot = np.zeros(sample_rate, dtype=np.int16)
    bot[3000:4000] = 4000

    user_path = tmp_path / "user.wav"
    bot_path = tmp_path / "bot.wav"
    telephony_stereo_path = tmp_path / "telephony_stereo.wav"
    wall_clock_stereo_path = tmp_path / "wall_stereo.wav"
    _write_test_wav(str(user_path), user, sample_rate)
    _write_test_wav(str(bot_path), bot, sample_rate)

    telephony_analysis, _ = merge_telephony_tracks_to_stereo(
        str(user_path),
        str(bot_path),
        output_path=str(telephony_stereo_path),
    )
    wall_analysis, _ = merge_wall_clock_tracks_to_stereo(
        str(user_path),
        str(bot_path),
        output_path=str(wall_clock_stereo_path),
    )

    assert wall_analysis.bot_delay_samples == 0
    assert wall_analysis.reason == "wall_clock_stereo"
    assert telephony_analysis.bot_delay_samples >= int(sample_rate * 0.4)

    with wave.open(str(wall_clock_stereo_path), "rb") as wf:
        frames = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).reshape(-1, 2)
    bot_channel = frames[:, 1]
    bot_start = int(np.argmax(np.abs(bot_channel) > 0))
    assert bot_start == 3000
