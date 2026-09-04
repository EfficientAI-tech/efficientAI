"""Tests for telephony dual-track alignment and merge."""

import numpy as np

from app.services.voice_agent.utils.telephony_audio_align import (
    TelephonyMergeStrategy,
    analyze_dual_tracks,
    merge_telephony_tracks_to_mono,
    mix_aligned_mono,
    read_wav_mono,
    write_wav_mono,
)


def _write_tone(path: str, *, sample_rate: int, start_sample: int, duration_samples: int, freq: float):
    total = start_sample + duration_samples
    t = np.arange(total, dtype=np.float32) / sample_rate
    signal = np.zeros(total, dtype=np.float32)
    segment = np.sin(2 * np.pi * freq * t[start_sample:total])
    signal[start_sample:total] = segment * 16000
    write_wav_mono(path, signal.astype(np.int16), sample_rate)


def test_mix_aligned_mono_applies_bot_delay():
    sample_rate = 8000
    user = np.zeros(sample_rate, dtype=np.int16)
    user[100:200] = 1000
    bot = np.zeros(sample_rate // 2, dtype=np.int16)
    bot[50:150] = 2000
    merged = mix_aligned_mono(user, bot, bot_delay_samples=100)
    # Bot track is delayed by 100 samples: bot[50] lands at merged index 150.
    assert merged[150] == 3000
    # User-only sample before delayed bot overlaps (indices 100–149).
    assert merged[120] == 1000
    assert merged[50] == 0


def test_analyze_chooses_user_only_when_bot_track_too_short():
    sample_rate = 8000
    bot = np.zeros(sample_rate // 40, dtype=np.int16)
    user = np.zeros(sample_rate, dtype=np.int16)
    user[400:800] = 5000
    analysis = analyze_dual_tracks(user, bot, sample_rate=sample_rate, call_direction="inbound")
    assert analysis.strategy == TelephonyMergeStrategy.USER_ONLY
    assert analysis.reason == "bot_track_too_short"


def test_analyze_keeps_aligned_mix_when_bot_leaks_during_bot_speech():
    sample_rate = 8000
    bot = np.zeros(sample_rate * 2, dtype=np.int16)
    bot[800:1600] = 6000
    user = np.zeros(sample_rate * 2, dtype=np.int16)
    user[820:1620] = (bot[800:1600] * 0.7).astype(np.int16)
    user[200:600] = 3000
    analysis = analyze_dual_tracks(user, bot, sample_rate=sample_rate, call_direction="outbound")
    assert analysis.strategy == TelephonyMergeStrategy.ALIGNED_MIX
    assert analysis.reason == "aligned_mix"


def test_merge_keeps_both_tracks_when_bot_leaks(tmp_path):
    sample_rate = 8000
    user_path = tmp_path / "user.wav"
    bot_path = tmp_path / "bot.wav"
    out_path = tmp_path / "out.wav"

    bot = np.zeros(sample_rate * 2, dtype=np.int16)
    bot[800:1600] = 6000
    user = np.zeros(sample_rate * 2, dtype=np.int16)
    user[820:1620] = (bot[800:1600] * 0.7).astype(np.int16)
    user[200:600] = 3000
    write_wav_mono(str(user_path), user, sample_rate)
    write_wav_mono(str(bot_path), bot, sample_rate)

    analysis, _duration = merge_telephony_tracks_to_mono(
        str(user_path),
        str(bot_path),
        output_path=str(out_path),
        call_direction="outbound",
    )
    assert analysis.strategy == TelephonyMergeStrategy.ALIGNED_MIX
    merged, _ = read_wav_mono(str(out_path))
    assert np.any(merged[800:1600] != 0)
    assert np.any(merged[200:600] != 0)


def test_merge_with_delayed_bot_track(tmp_path):
    sample_rate = 8000
    user_path = tmp_path / "user.wav"
    bot_path = tmp_path / "bot.wav"
    out_path = tmp_path / "out.wav"

    _write_tone(str(user_path), sample_rate=sample_rate, start_sample=0, duration_samples=400, freq=440)
    _write_tone(str(bot_path), sample_rate=sample_rate, start_sample=0, duration_samples=400, freq=880)

    bot_raw, _ = read_wav_mono(str(bot_path))
    bot_padded = np.pad(bot_raw, (200, 0), mode="constant")
    write_wav_mono(str(bot_path), bot_padded, sample_rate)

    analysis, duration = merge_telephony_tracks_to_mono(
        str(user_path),
        str(bot_path),
        output_path=str(out_path),
    )
    assert duration > 0
    assert analysis.strategy == TelephonyMergeStrategy.ALIGNED_MIX
    merged, _ = read_wav_mono(str(out_path))
    user, _ = read_wav_mono(str(user_path))
    assert len(merged) >= len(user)
