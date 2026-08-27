"""Tests for dual-track merge and upload fallbacks."""

import wave

import numpy as np
import pytest

from app.services.voice_agent.utils import audio_merge as audio_merge_module
from app.services.voice_agent.utils.audio_merge import merge_and_upload_audio


def _write_wav(path: str, *, num_samples: int) -> None:
    samples = (np.sin(np.linspace(0, 4 * np.pi, num_samples)) * 16000).astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(8000)
        wf.writeframes(samples.tobytes())


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
