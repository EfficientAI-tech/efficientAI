"""Tests for dual-track merge and upload fallbacks."""

import wave

import numpy as np
import pytest

from efficientai.audio.utils import mix_audio

from app.services.voice_agent.utils import audio_merge as audio_merge_module
from app.services.voice_agent.utils.audio_merge import merge_and_upload_audio
from app.services.voice_agent.utils.telephony_audio_align import (
    merge_telephony_tracks_to_mono,
    read_wav_mono,
    write_wav_mono,
)


def _write_wav(path: str, *, num_samples: int) -> None:
    samples = (np.sin(np.linspace(0, 4 * np.pi, num_samples)) * 16000).astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(8000)
        wf.writeframes(samples.tobytes())


def test_mix_audio_doubles_user_when_present_in_both_mixed_streams():
    """Documents the old playground bug: mixing two already-mixed mono streams."""
    user_only = np.full(800, 5000, dtype=np.int16).tobytes()
    bot_only = np.full(800, 3000, dtype=np.int16).tobytes()
    input_mix = mix_audio(user_only, bot_only)
    remixed = mix_audio(input_mix, user_only)
    input_samples = np.frombuffer(input_mix, dtype=np.int16)
    remixed_samples = np.frombuffer(remixed, dtype=np.int16)
    assert remixed_samples[0] > input_samples[0]
    assert remixed_samples[0] == 13000  # (5000+3000) + 5000


def test_merge_dual_tracks_does_not_double_isolated_user_track(tmp_path):
    """Disk merge with an empty bot track uploads user audio without doubling."""
    sample_rate = 8000
    user_path = tmp_path / "user.wav"
    bot_path = tmp_path / "bot.wav"
    out_path = tmp_path / "out.wav"

    user = np.zeros(sample_rate, dtype=np.int16)
    user[100:200] = 5000
    bot = np.zeros(sample_rate // 40, dtype=np.int16)
    write_wav_mono(str(user_path), user, sample_rate)
    write_wav_mono(str(bot_path), bot, sample_rate)

    analysis, _duration = merge_telephony_tracks_to_mono(
        str(user_path),
        str(bot_path),
        output_path=str(out_path),
        call_direction="inbound",
    )
    from app.services.voice_agent.utils.telephony_audio_align import TelephonyMergeStrategy

    assert analysis.strategy == TelephonyMergeStrategy.USER_ONLY
    merged, _rate = read_wav_mono(str(out_path))
    assert merged[150] == 5000
    assert merged[150] != 10000


def test_merge_and_upload_uses_bot_track_when_user_track_empty(tmp_path, monkeypatch):
    user_path = tmp_path / "user.wav"
    bot_path = tmp_path / "bot.wav"
    _write_wav(str(user_path), num_samples=10)
    _write_wav(str(bot_path), num_samples=800)

    uploads = []

    class _FakeS3:
        def upload_file(self, file_content, file_id, file_format, organization_id=None, evaluator_id=None, meaningful_id=None):
            uploads.append(
                {
                    "size": len(file_content),
                    "organization_id": organization_id,
                    "meaningful_id": meaningful_id,
                }
            )
            return f"audio/organizations/{organization_id}/audio/test.wav"

    monkeypatch.setattr(audio_merge_module, "s3_service", _FakeS3())

    s3_key, duration = merge_and_upload_audio(
        str(user_path),
        str(bot_path),
        call_start_time=0.0,
        organization_id="org-1",
        result_id="123456",
    )

    assert s3_key.endswith("test.wav")
    assert duration is not None
    assert len(uploads) == 1
    assert uploads[0]["size"] > 100
    assert not user_path.exists()
    assert not bot_path.exists()
