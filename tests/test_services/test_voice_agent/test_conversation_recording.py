"""Unit tests for synchronized conversation recording capture."""

import numpy as np
import pytest

from app.services.voice_agent.conversation_recording import (
    ConversationRecordingCapture,
    RecordingTimeline,
    _pad_and_append_pcm,
    upload_conversation_recording,
)


def test_pad_and_append_pcm_preserves_wall_clock_offset(monkeypatch):
    """Speech appended after a delay should begin at the correct timeline offset."""
    timeline = RecordingTimeline()
    timeline.start_time = 1000.0
    sample_rate = 8000
    buffer = bytearray()

    monkeypatch.setattr(
        "app.services.voice_agent.conversation_recording.time.time",
        lambda: 1001.0,
    )

    total = _pad_and_append_pcm(
        buffer,
        pcm=np.full(800, 1000, dtype=np.int16).tobytes(),
        timeline=timeline,
        sample_rate=sample_rate,
        total_samples_written=0,
    )

    assert total == 8000 + 800
    audio = np.frombuffer(bytes(buffer), dtype=np.int16)
    assert np.count_nonzero(audio[:8000]) == 0
    assert np.count_nonzero(audio[8000:]) > 0


def test_conversation_capture_has_audio_threshold():
    capture = ConversationRecordingCapture()
    capture.user_buffer.extend(b"\x01" * 200)
    capture.sample_rate = 24000

    assert capture.has_audio()
    assert len(capture.user_audio) == 200


def test_upload_conversation_recording_uses_aligned_stereo(monkeypatch):
    import sys
    import types

    sample_rate = 8000
    duration = sample_rate
    t = np.linspace(0, 1, duration, endpoint=False)
    user = (np.sin(2 * np.pi * 220 * t) * 10000).astype(np.int16)
    bot = (np.sin(2 * np.pi * 440 * t) * 8000).astype(np.int16)

    capture = ConversationRecordingCapture()
    capture.user_buffer.extend(user.tobytes())
    capture.bot_buffer.extend(bot.tobytes())
    capture.sample_rate = sample_rate

    uploaded: list[tuple] = []

    def fake_upload(file_content, file_id, file_format, organization_id, evaluator_id, meaningful_id):
        uploaded.append((meaningful_id, len(file_content), file_format))
        return f"s3://test/{meaningful_id}.wav"

    class FakeAnalysis:
        strategy = type("S", (), {"value": "aligned_mix"})()
        reason = "test"
        correlation_peak = 0.9

    def fake_stereo(_user_path, _bot_path, *, output_path):
        with open(output_path, "wb") as f:
            f.write(b"RIFF" + b"\x00" * 44)
        return FakeAnalysis(), 1.0

    def fake_mono(_user_path, _bot_path, *, output_path):
        with open(output_path, "wb") as f:
            f.write(b"RIFF" + b"\x00" * 44)
        return FakeAnalysis(), 1.0

    fake_align = types.SimpleNamespace(
        merge_wall_clock_tracks_to_stereo=fake_stereo,
        merge_wall_clock_tracks_to_mono=fake_mono,
    )
    monkeypatch.setitem(
        sys.modules,
        "app.services.voice_agent.utils.telephony_audio_align",
        fake_align,
    )
    monkeypatch.setattr(
        "app.services.voice_agent.conversation_recording.s3_service.upload_file",
        fake_upload,
    )

    primary_key, duration_secs, metadata = upload_conversation_recording(
        capture,
        call_start_time=0.0,
        prefer_stereo=True,
    )

    assert primary_key is not None
    assert duration_secs > 0
    assert metadata["recording_format"] == "stereo"
    assert metadata.get("stereo_recording_s3_key")
    assert metadata.get("mono_recording_s3_key")
    assert metadata.get("user_recording_s3_key")
    assert metadata.get("bot_recording_s3_key")
    assert metadata.get("merge_strategy") == "aligned_mix"
    assert metadata.get("align_mode") == "wall_clock"
    assert len(uploaded) >= 4
